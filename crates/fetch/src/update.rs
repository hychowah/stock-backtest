//! `bt data update`: the stages of an update and their one writer.
//!
//! Each market (the US, then Hong Kong) runs its stages in turn: companies,
//! reports, prices. A stage's items (a report of one company, one history)
//! go to IN_FLIGHT worker threads, which ask the provider, read the saved
//! file and merge the reply through the typed files of `market_data::raw`.
//! The calling thread is the one writer: it saves each merged file, records
//! the item in the journal, and keeps the record (`data/update.json`). A
//! watcher thread turns a stop (the caller's flag or `data/update.stop`)
//! into the provider's stop flag, which ends waits and drops late replies,
//! and writes `stopping` to the record at once.

use crate::plan::{self, Reports, Saved};
use crate::provider::{self, Endpoint, Failure, IN_FLIGHT, Provider, Reason};
use chrono::{DateTime, FixedOffset, NaiveDate, Utc};
use market_data::commands::{self, Home, PrepareReply, PrepareRequest};
use market_data::raw::{History, HistoryFile, ItemError, KeyMetrics, Listing, PyJson, Raw, StatementKind, Statements, Universe, Window};
use market_data::updates::{self, Journal, UpdateLock, UpdateProgress, UpdateRecord, UpdateStage, UpdateState};
use market_data::{Error, Market};
use serde::Serialize;
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Mutex, mpsc};
use std::time::{Duration, Instant};

/// `bt data update [--as-of T]`.
pub struct UpdateRequest {
    /// The update's clock: it sets the last price day, the Hong Kong date of
    /// the report check, and the time preparation runs at. `bt` supplies the
    /// current time when none is given.
    pub as_of: DateTime<FixedOffset>,
}

/// The update's record at its end, and what preparation published.
#[derive(Debug, Serialize)]
pub struct UpdateReply {
    /// `state` is stopped, failed, partial or complete.
    #[serde(flatten)]
    pub progress: UpdateProgress,
    /// One entry for each prepared market; none when preparation did not
    /// run or failed.
    pub prepared: Option<PrepareReply>,
}

/// The record keeps the first failed items.
const NAMED_FAILURES: usize = 20;
/// The record is written at most this often while items come in.
const WRITE_EVERY: Duration = Duration::from_secs(1);
/// How often the watcher looks for a stop.
const WATCH_EVERY: Duration = Duration::from_millis(100);

/// `bt data update`: brings raw/ up to date for the US and Hong Kong, then
/// prepares every market at `as_of`. The target: prices through the last day
/// whose 22:00 UTC has passed; reports when the Hong Kong date is a Saturday
/// not yet checked, or the last check is over 7 days old or missing; delisted
/// companies too when the last full sweep is over 90 days old or missing. An
/// unfinished update (running, stopped or failed) with the same last day
/// continues with its report check: its journal's items are not asked again.
/// A failed item keeps its file, is named in the record and makes the update
/// partial; a saved history that cannot be read is asked whole and replaced
/// (a statements file that cannot be read fails its item); a refused key (401), a missing key file, a company list that
/// cannot be read or a failed write ends the downloads, and the saved data is
/// still prepared, but the update is failed. A stop ends after the requests
/// in flight, keeps what is saved and skips preparation; a stop during
/// preparation lets preparation finish.
///
/// Holds `data/update.lock` from start to end. Fails with "an update is
/// already running" when another update holds the lock, and with an error
/// when the home has no US or Hong Kong company list. The record says
/// running, with this process id, before any large file is read. It says
/// stopping within about 0.1 s of a stop. It gets the final state (stopped,
/// failed, partial or complete) only as the last write before the lock is
/// released. Tokyo's files are never touched.
pub fn update(home: &Home, request: &UpdateRequest, stop: &AtomicBool) -> Result<UpdateReply, Error> {
    let _lock = UpdateLock::take(home)?;
    let raw = Raw::new(home.raw());
    let markets: Vec<Market> = [Market::Us, Market::Hk].into_iter().filter(|&m| raw.present(m)).collect();
    if markets.is_empty() {
        return Err(Error::new("no company list to update: the home has no US or Hong Kong raw data", home.raw().display()));
    }
    let previous = UpdateRecord::read(home)?.unwrap_or_default();
    let (end, today) = (plan::last_day(request.as_of), plan::hong_kong_date(request.as_of));
    let memory = &previous.memory;
    let fresh = Reports::decide(
        today,
        memory.last_report_check.map(plan::date),
        memory.last_full_sweep.map(plan::date),
    );
    let unfinished = |p: &&UpdateProgress| {
        p.end == plan::day(end) && matches!(p.state, UpdateState::Running | UpdateState::Stopping | UpdateState::Stopped | UpdateState::Failed)
    };
    let continued = previous.progress.as_ref().filter(unfinished);
    let reports = continued.map_or(fresh, |p| Reports::continued(p.reports, fresh));
    let resume = continued.is_some();

    let (halt, stopping, downloading) = (AtomicBool::new(false), AtomicBool::new(false), AtomicBool::new(true));
    let progress = UpdateProgress {
        state: UpdateState::Running,
        pid: std::process::id(),
        stage: None,
        market: None,
        done: 0,
        total: 0,
        failed: 0,
        failures: Vec::new(),
        started: now(),
        finished: None,
        end: plan::day(end),
        reports: reports.check(),
        error: None,
    };
    // The record names this process before any large file is read, so a
    // caller that started the command sees it running at once.
    let record = UpdateRecord { memory: previous.memory.clone(), progress: Some(progress) };
    record.write(home)?;
    let shared = Mutex::new(record.clone());
    let mut run = Run {
        home,
        record,
        shared: &shared,
        journal: Journal::open(home, plan::day(end), resume)?,
        reports,
        halt: &halt,
        stopping: &stopping,
        report_failures: 0,
        written: Instant::now(),
    };
    let key_file = provider::key_file();
    let client = Provider::new(&provider::address(), &key_file, &halt);
    let source = Source { provider: &client, raw, end, key_file };
    let ended = std::thread::scope(|scope| {
        scope.spawn(|| {
            while downloading.load(Ordering::Relaxed) {
                if !stopping.load(Ordering::Relaxed) && (stop.load(Ordering::Relaxed) || updates::stop_requested(home)) {
                    stopping.store(true, Ordering::Relaxed);
                    halt.store(true, Ordering::Relaxed);
                    // Says stopping at once, while the requests in flight
                    // end. A failed write here is met again by the writer's
                    // next write.
                    let mut record = shared.lock().unwrap();
                    if let Some(progress) = record.progress.as_mut().filter(|p| p.state == UpdateState::Running) {
                        progress.state = UpdateState::Stopping;
                        let _ = record.write(home);
                    }
                }
                std::thread::sleep(WATCH_EVERY);
            }
        });
        // Ends the watcher also when the downloads panic, so that the panic
        // ends the process and frees the lock.
        let _done = Done(&downloading);
        markets.iter().try_for_each(|&market| run.market(&source, market))
    });
    run.finish(ended, today, &request.as_of)
}

/// Clears its flag when dropped.
struct Done<'a>(&'a AtomicBool);

impl Drop for Done<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Relaxed);
    }
}

fn now() -> String {
    Utc::now().to_rfc3339()
}

/// Why downloads ended early.
enum Halt {
    Stopped,
    Failed(Error),
}

impl From<Error> for Halt {
    fn from(e: Error) -> Halt {
        Halt::Failed(e)
    }
}

/// Why a worker has no result for an item.
enum Miss {
    /// The item failed; its file stays.
    Failed(ItemError),
    /// The downloads must end.
    Fatal(Error),
    /// A stop ended the request.
    Stopped,
}

impl From<ItemError> for Miss {
    fn from(e: ItemError) -> Miss {
        Miss::Failed(e)
    }
}

/// What the workers share: the client and the raw files to read.
struct Source<'a> {
    provider: &'a Provider<'a>,
    raw: Raw,
    end: NaiveDate,
    key_file: PathBuf,
}

impl Source<'_> {
    /// Asks the provider and reads the reply. `place` is the file the item
    /// changes, named when it fails.
    fn ask(&self, endpoint: &Endpoint, place: &Path) -> Result<PyJson, Miss> {
        let body = self.provider.get(endpoint).map_err(|failure| match self.halt(failure) {
            Ok(failure) => Miss::Failed(ItemError { message: failure.to_string(), place: place.display().to_string() }),
            Err(Halt::Stopped) => Miss::Stopped,
            Err(Halt::Failed(e)) => Miss::Fatal(e),
        })?;
        // The parse error is not kept: it could quote the body.
        PyJson::parse(&body).map_err(|_| {
            let message = format!("{endpoint}: the provider's reply is not JSON that the raw files can hold");
            Miss::Failed(ItemError { message, place: place.display().to_string() })
        })
    }

    /// A failure that ends the downloads (a stop, a refused key or no key
    /// file) as a halt; any other failure is the item's.
    fn halt(&self, failure: Failure) -> Result<Failure, Halt> {
        match failure.reason {
            Reason::Stopped => Err(Halt::Stopped),
            Reason::NoKey | Reason::Status(401) => Err(Halt::Failed(Error::new(failure.to_string(), self.key_file.display()))),
            _ => Ok(failure),
        }
    }

    /// One company list page; any failure ends the downloads.
    fn page(&self, endpoint: &Endpoint, place: &Path) -> Result<PyJson, Halt> {
        self.ask(endpoint, place).map_err(|miss| match miss {
            Miss::Failed(e) => Halt::Failed(e.into()),
            Miss::Fatal(e) => Halt::Failed(e),
            Miss::Stopped => Halt::Stopped,
        })
    }

    /// A company's reply of one report endpoint, merged into its saved file.
    fn report(&self, symbol: &str, kind: StatementKind) -> Result<(Statements, PyJson), Miss> {
        let owned = symbol.to_string();
        let endpoint = match kind {
            StatementKind::Income => Endpoint::IncomeStatement { symbol: owned },
            StatementKind::Balance => Endpoint::BalanceSheetStatement { symbol: owned },
            StatementKind::CashFlow => Endpoint::CashFlowStatement { symbol: owned },
            StatementKind::KeyMetrics => Endpoint::KeyMetrics { symbol: owned },
            StatementKind::Ratios => Endpoint::Ratios { symbol: owned },
        };
        let reply = self.ask(&endpoint, &self.raw.statement(kind.endpoint(), symbol))?;
        let mut statements = Statements::load(&self.raw, kind, symbol)?;
        statements.apply(&reply)?;
        Ok((statements, reply))
    }

    /// A history with its recent windows applied, or, when they change a
    /// saved adjusted close, the whole history asked again.
    fn history(&self, file: &HistoryFile) -> Result<History, Miss> {
        // A saved history that cannot be read is asked whole and replaced,
        // so that it cannot stop preparation night after night.
        let mut history = History::load(&self.raw, file).unwrap_or_else(|_| History::missing(&self.raw, file));
        let monthly = *file == HistoryFile::Treasury;
        let saved = match (history.first(), history.last()) {
            _ if !history.exists() => Saved::Missing,
            (Some(first), Some(last)) => Saved::Rows(plan::date(first), plan::date(last)),
            _ => Saved::Empty,
        };
        let recent = self.windows(&history, file, plan::windows(saved, self.end, monthly))?;
        if history.changes_closes(&recent)? {
            let first = plan::date(history.first().expect("a history with saved closes"));
            let whole = self.windows(&history, file, plan::whole(first, self.end, monthly))?;
            history.check_whole(&recent, &whole)?;
            history.apply(whole);
        } else {
            history.apply(recent);
        }
        Ok(history)
    }

    /// Asks and admits the windows in turn; the first failure ends the item.
    fn windows(&self, history: &History, file: &HistoryFile, spans: Vec<(NaiveDate, NaiveDate)>) -> Result<Vec<Window>, Miss> {
        let place = file.path(&self.raw);
        spans
            .into_iter()
            .map(|(from, to)| {
                let reply = self.ask(&series(file, from, to), &place)?;
                Ok(history.admit(reply, plan::day(from), plan::day(to))?)
            })
            .collect()
    }
}

/// The request of one window of a history.
fn series(file: &HistoryFile, from: NaiveDate, to: NaiveDate) -> Endpoint {
    let full = |symbol: String| Endpoint::Full { symbol, from, to };
    match file {
        HistoryFile::Prices(symbol) => Endpoint::DividendAdjusted { symbol: symbol.clone(), from, to },
        HistoryFile::Spy => Endpoint::DividendAdjusted { symbol: "SPY".to_string(), from, to },
        HistoryFile::Native(symbol) => full(symbol.clone()),
        HistoryFile::Calendar(Market::Hk) => full("^HSI".to_string()),
        HistoryFile::Calendar(market) => panic!("the {} calendar is not updated", market.id()),
        HistoryFile::Fx(currency) => full(format!("USD{currency}")),
        HistoryFile::Treasury => Endpoint::TreasuryRates { from, to },
    }
}

/// Runs `fetch` on the items on IN_FLIGHT worker threads and gives each
/// result to `write` on this thread, in the order they come. Workers take no
/// item once `halt` is set. A write error sets it, and later results are
/// dropped.
fn parallel<T: Sync, R: Send>(
    items: &[T],
    halt: &AtomicBool,
    fetch: impl Fn(&T) -> R + Sync,
    mut write: impl FnMut(&T, R) -> Result<(), Error>,
) -> Result<(), Error> {
    let next = AtomicUsize::new(0);
    let (sender, receiver) = mpsc::channel();
    std::thread::scope(|scope| {
        for _ in 0..IN_FLIGHT.min(items.len()) {
            let (sender, next, fetch) = (sender.clone(), &next, &fetch);
            scope.spawn(move || {
                while !halt.load(Ordering::Relaxed) {
                    let i = next.fetch_add(1, Ordering::Relaxed);
                    if i >= items.len() || sender.send((i, fetch(&items[i]))).is_err() {
                        break;
                    }
                }
            });
        }
        drop(sender);
        let mut error = None;
        for (i, result) in receiver {
            if error.is_none()
                && let Err(e) = write(&items[i], result)
            {
                halt.store(true, Ordering::Relaxed);
                error = Some(e);
            }
        }
        error.map_or(Ok(()), Err)
    })
}

/// The writer's state.
struct Run<'a> {
    home: &'a Home,
    /// The record as the writer keeps it.
    record: UpdateRecord,
    /// The record as last written. The watcher also writes it, once, to say
    /// stopping; the lock keeps the two writes apart.
    shared: &'a Mutex<UpdateRecord>,
    journal: Journal,
    reports: Reports,
    halt: &'a AtomicBool,
    /// Set by the watcher when a stop was asked.
    stopping: &'a AtomicBool,
    report_failures: u64,
    written: Instant,
}

impl Run<'_> {
    fn progress(&mut self) -> &mut UpdateProgress {
        self.record.progress.as_mut().expect("an update's record has progress")
    }

    /// Writes the record; once the watcher has seen a stop, it says
    /// stopping.
    fn write(&mut self) -> Result<(), Error> {
        let mut shared = self.shared.lock().unwrap();
        if self.stopping.load(Ordering::Relaxed) && self.progress().state == UpdateState::Running {
            self.progress().state = UpdateState::Stopping;
        }
        self.written = Instant::now();
        *shared = self.record.clone();
        shared.write(self.home)
    }

    /// Writes the record at most once a second.
    fn tick(&mut self) -> Result<(), Error> {
        if self.written.elapsed() >= WRITE_EVERY { self.write() } else { Ok(()) }
    }

    fn begin(&mut self, stage: UpdateStage, market: Option<Market>, total: usize) -> Result<(), Error> {
        let progress = self.progress();
        (progress.stage, progress.market, progress.done, progress.total) = (Some(stage), market, 0, total as u64);
        self.write()
    }

    /// A raw file's journal item: its path below `raw/`.
    fn item(&self, path: &Path) -> String {
        path.strip_prefix(self.home.raw()).unwrap_or(path).display().to_string()
    }

    /// Counts a worker's result; `None` for a failed or stopped item.
    fn take<T>(&mut self, got: Result<T, Miss>, report: bool) -> Result<Option<T>, Error> {
        match got {
            Ok(value) => {
                self.progress().done += 1;
                Ok(Some(value))
            }
            Err(Miss::Failed(e)) => {
                self.report_failures += u64::from(report);
                let place = Path::new(&e.place).strip_prefix(self.home.root()).map_or(e.place.clone(), |p| p.display().to_string());
                let progress = self.progress();
                progress.done += 1;
                progress.failed += 1;
                if progress.failures.len() < NAMED_FAILURES {
                    progress.failures.push(Error::new(e.message, place));
                }
                self.tick()?;
                Ok(None)
            }
            Err(Miss::Fatal(e)) => Err(e),
            Err(Miss::Stopped) => Ok(None),
        }
    }

    /// Records a saved item and counts it.
    fn saved(&mut self, item: &str) -> Result<(), Error> {
        self.journal.record(item)?;
        self.tick()
    }

    fn halted(&self) -> Result<(), Halt> {
        if self.halt.load(Ordering::Relaxed) { Err(Halt::Stopped) } else { Ok(()) }
    }

    fn market(&mut self, source: &Source, market: Market) -> Result<(), Halt> {
        let universe = self.companies(source, market)?;
        self.halted()?;
        match market {
            Market::Us => self.us(source, &universe),
            _ => self.hong_kong(source, &universe),
        }
    }

    fn us(&mut self, source: &Source, universe: &Universe) -> Result<(), Halt> {
        let raw = &source.raw;
        let mut metrics = KeyMetrics::load(raw)?;
        let pending = self.record.memory.pending.us.clone();
        let mut targets = plan::price_targets(universe, &pending, |symbol| {
            raw.prices(symbol).exists() || raw.statement(StatementKind::Income.endpoint(), symbol).exists()
        });
        if self.reports.due {
            let wanted = plan::report_set(universe, &pending, self.reports.sweep);
            self.key_metrics(source, &wanted, &mut metrics, &mut targets)?;
            self.halted()?;
            let kinds = [StatementKind::Income, StatementKind::Balance, StatementKind::CashFlow, StatementKind::Ratios];
            let items = wanted.iter().filter(|s| targets.contains(*s)).flat_map(|s| kinds.map(|k| (s.clone(), k))).collect();
            self.statements(source, items, None)?;
            self.halted()?;
        }
        let mut files = vec![HistoryFile::Spy, HistoryFile::Treasury];
        files.extend(targets.iter().map(|s| HistoryFile::Prices(s.clone())));
        self.prices(source, Market::Us, files)?;
        self.halted()?;
        // A pending company leaves when it has prices, key metrics and
        // rows in all five report files.
        let leaves = |symbol: &String| {
            History::load(raw, &HistoryFile::Prices(symbol.clone())).is_ok_and(|h| !h.is_empty())
                && metrics.rows(symbol).is_some_and(|rows| !rows.is_empty())
                && StatementKind::US.iter().all(|&k| Statements::load(raw, k, symbol).is_ok_and(|s| !s.rows().is_empty()))
        };
        self.record.memory.pending.us.retain(|symbol| !leaves(symbol));
        Ok(self.write()?)
    }

    fn hong_kong(&mut self, source: &Source, universe: &Universe) -> Result<(), Halt> {
        let raw = &source.raw;
        let pending = self.record.memory.pending.hk.clone();
        let report_set = plan::report_set(universe, &pending, self.reports.sweep);
        let targets = plan::price_targets(universe, &pending, |symbol| raw.prices(symbol).exists());
        if self.reports.due {
            let items = report_set.iter().flat_map(|s| StatementKind::FOREIGN.map(|k| (s.clone(), k))).collect();
            self.statements(source, items, Some(Market::Hk))?;
            self.halted()?;
        }
        let listing = targets.iter().map(|symbol| {
            let currency = universe.get(symbol).and_then(|row| row.get("currency")).filter(|c| c.truthy());
            currency.and_then(PyJson::as_str).unwrap_or("HKD")
        });
        let symbols: BTreeSet<&String> = report_set.iter().chain(&targets).collect();
        let mut codes = Vec::new();
        for symbol in symbols {
            for kind in StatementKind::FOREIGN {
                let Ok(statements) = Statements::load(raw, kind, symbol) else { continue };
                codes.extend(statements.rows().iter().filter_map(|row| row.get("reportedCurrency")?.as_str().map(str::to_string)));
            }
        }
        let currencies = plan::fx_currencies(listing, codes.iter().map(String::as_str));
        let mut files = vec![HistoryFile::Calendar(Market::Hk)];
        files.extend(currencies.into_iter().map(HistoryFile::Fx));
        files.extend(targets.iter().flat_map(|s| [HistoryFile::Prices(s.clone()), HistoryFile::Native(s.clone())]));
        self.prices(source, Market::Hk, files)?;
        self.halted()?;
        // A pending company leaves when it has prices and its three
        // statements files, even with no rows.
        let leaves = |symbol: &String| {
            History::load(raw, &HistoryFile::Prices(symbol.clone())).is_ok_and(|h| !h.is_empty())
                && StatementKind::FOREIGN.iter().all(|&k| Statements::load(raw, k, symbol).is_ok_and(|s| s.exists()))
        };
        self.record.memory.pending.hk.retain(|symbol| !leaves(symbol));
        Ok(self.write()?)
    }

    /// Asks the market's company list and merges it into the saved one; the
    /// new companies become pending, saved in the record before the list.
    /// Any failure ends the downloads.
    fn companies(&mut self, source: &Source, market: Market) -> Result<Universe, Halt> {
        let mut universe = Universe::load(&source.raw, market)?;
        let path = source.raw.universe(market);
        let item = self.item(&path);
        if self.journal.contains(&item) {
            return Ok(universe);
        }
        self.begin(UpdateStage::Companies, Some(market), 1)?;
        let mut listing = Listing::new(market);
        let fail = |message: &str| Halt::Failed(Error::new(message, path.display()));
        // Paging ends at a short page; a list that fills every page is refused.
        let screener = |listing: &mut Listing, exchange: &str, active: bool| -> Result<usize, Halt> {
            let mut returned = 0;
            for page in 0..30 {
                let endpoint = Endpoint::CompanyScreener { exchange: exchange.to_string(), active, page };
                let rows = listing.screener(exchange, active, &source.page(&endpoint, &path)?)?;
                returned += rows;
                if rows < 1000 {
                    return Ok(returned);
                }
            }
            Err(fail(&format!("{exchange} has more than 30 pages of companies; the saved list was kept")))
        };
        if market == Market::Us {
            for exchange in ["NYSE", "NASDAQ", "AMEX"] {
                if screener(&mut listing, exchange, true)? == 0 {
                    return Err(fail(&format!("{exchange} returned no companies; the saved list was kept")));
                }
            }
            if listing.is_empty() {
                return Err(fail("the provider returned no US company; the saved list was kept"));
            }
            for page in 0..1000 {
                if listing.delisted(&source.page(&Endpoint::DelistedCompanies { page }, &path)?)? < 100 {
                    break;
                }
                if page == 999 {
                    return Err(fail("the delisted list has more than 1,000 pages; the saved list was kept"));
                }
            }
        } else {
            for active in [true, false] {
                screener(&mut listing, "HKSE", active)?;
            }
            if listing.is_empty() {
                return Err(fail("the provider returned no Hong Kong company; the saved list was kept"));
            }
        }
        let new = universe.apply(listing);
        let pending = match market {
            Market::Us => &mut self.record.memory.pending.us,
            _ => &mut self.record.memory.pending.hk,
        };
        pending.extend(new);
        pending.sort();
        pending.dedup();
        self.write()?;
        universe.save()?;
        self.progress().done = 1;
        self.saved(&item)?;
        Ok(universe)
    }

    /// The US key metrics of `wanted`: each reply is saved as its
    /// statements file, and its new rows are kept for `metrics.jsonl`, which
    /// is saved once, at the end or at a stop. A company that gains a report
    /// becomes pending and a price target. Its journal item is recorded only
    /// after `metrics.jsonl` is saved, so a crash asks it again.
    fn key_metrics(
        &mut self,
        source: &Source,
        wanted: &[String],
        metrics: &mut KeyMetrics,
        targets: &mut BTreeSet<String>,
    ) -> Result<(), Halt> {
        let path = |symbol: &str| source.raw.statement(StatementKind::KeyMetrics.endpoint(), symbol);
        let items: Vec<&String> = wanted.iter().filter(|s| !self.journal.contains(&self.item(&path(s)))).collect();
        self.begin(UpdateStage::Reports, Some(Market::Us), items.len())?;
        let mut done = Vec::new();
        let halt = self.halt;
        let asked = parallel(&items, halt, |symbol| source.report(symbol, StatementKind::KeyMetrics), |&symbol, got| {
            let Some((mut statements, reply)) = self.take(got, true)? else { return Ok(()) };
            statements.save()?;
            let before = metrics.rows(symbol).is_some_and(|rows| plan::reported(&rows));
            let rows = reply.as_list().expect("an admitted reply is a list");
            if metrics.apply(symbol, rows) && !targets.contains(symbol) && !before && plan::reported(&metrics.rows(symbol).unwrap()) {
                targets.insert(symbol.clone());
                let pending = &mut self.record.memory.pending.us;
                pending.push(symbol.clone());
                pending.sort();
                self.write()?;
            }
            done.push(self.item(&path(symbol)));
            self.tick()
        });
        let saved = metrics.save().map(drop);
        let recorded = saved.and_then(|()| done.iter().try_for_each(|item| self.journal.record(item)));
        asked.and(recorded)?;
        Ok(())
    }

    /// The statements items, each a company and an endpoint. `market` is
    /// the stage's market when the stage is new; `None` continues the US
    /// reports stage after its key metrics.
    fn statements(&mut self, source: &Source, items: Vec<(String, StatementKind)>, market: Option<Market>) -> Result<(), Halt> {
        let path = |(symbol, kind): &(String, StatementKind)| source.raw.statement(kind.endpoint(), symbol);
        let items: Vec<_> = items.into_iter().filter(|item| !self.journal.contains(&self.item(&path(item)))).collect();
        match market {
            Some(market) => self.begin(UpdateStage::Reports, Some(market), items.len())?,
            None => self.progress().total += items.len() as u64,
        }
        let halt = self.halt;
        parallel(&items, halt, |(symbol, kind)| source.report(symbol, *kind), |item, got| {
            let Some((mut statements, _)) = self.take(got, true)? else { return Ok(()) };
            statements.save()?;
            self.saved(&self.item(&path(item)))
        })?;
        Ok(())
    }

    /// The histories, each asked through the last day.
    fn prices(&mut self, source: &Source, market: Market, files: Vec<HistoryFile>) -> Result<(), Halt> {
        let items: Vec<_> = files.into_iter().filter(|f| !self.journal.contains(&self.item(&f.path(&source.raw)))).collect();
        self.begin(UpdateStage::Prices, Some(market), items.len())?;
        let halt = self.halt;
        parallel(&items, halt, |file| source.history(file), |file, got| {
            let Some(mut history) = self.take(got, false)? else { return Ok(()) };
            history.save()?;
            self.saved(&self.item(&file.path(&source.raw)))
        })?;
        Ok(())
    }

    /// Ends the update: a stop skips preparation; otherwise the report dates
    /// advance when downloads ended with no failed report item, and every
    /// market is prepared.
    fn finish(mut self, ended: Result<(), Halt>, today: NaiveDate, as_of: &DateTime<FixedOffset>) -> Result<UpdateReply, Error> {
        let mut error = match ended {
            Err(Halt::Stopped) => {
                let progress = self.progress();
                (progress.state, progress.finished) = (UpdateState::Stopped, Some(now()));
                self.write()?;
                return Ok(UpdateReply { progress: self.record.progress.unwrap(), prepared: None });
            }
            Err(Halt::Failed(e)) => Some(e),
            Ok(()) => {
                if self.reports.due && self.report_failures == 0 {
                    let memory = &mut self.record.memory;
                    memory.last_report_check = Some(plan::day(today));
                    if self.reports.sweep {
                        memory.last_full_sweep = Some(plan::day(today));
                    }
                }
                None
            }
        };
        // Preparation runs whatever is asked now, so the record says running
        // until its end. The final state is the last write before the lock
        // is released: a caller that reads it may start the next update.
        self.stopping.store(false, Ordering::Relaxed);
        self.progress().state = UpdateState::Running;
        self.begin(UpdateStage::Preparing, None, 0)?;
        let prepared = commands::prepare(self.home, &PrepareRequest { as_of: *as_of }).map_err(|e| error.get_or_insert(e).clone()).ok();
        let finished = now();
        let progress = self.progress();
        progress.state = match (&error, progress.failed) {
            (Some(_), _) => UpdateState::Failed,
            (None, 0) => UpdateState::Complete,
            (None, _) => UpdateState::Partial,
        };
        let complete = progress.state == UpdateState::Complete;
        (progress.finished, progress.error) = (Some(finished.clone()), error.take());
        if complete {
            self.record.memory.last_success = Some(finished);
        }
        self.write()?;
        Ok(UpdateReply { progress: self.record.progress.unwrap(), prepared })
    }
}
