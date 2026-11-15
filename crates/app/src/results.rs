//! The routes that read a complete run's result file with the engine's
//! views. Their rows are those of `bt export tables`, without `case`, except
//! that the holdings are those of `bt export holdings` (with their `source:`
//! fields), the sector spread is the `sectors` rows of trial `all` without
//! that trial, an attribution lists its top holdings, and one trial's
//! sectors are the weights of each period ([`views::sector_weights`]). The
//! page writes its CSV files from these rows. A route about one trial reads
//! only that trial's rows.

use crate::http::{App, Failure, Id, blocking};
use axum::extract::rejection::QueryRejection;
use axum::extract::{Query, State};
use axum::routing::get;
use axum::{Json, Router};
use engine::results::{PeriodRow, ResultFile, StepRow, TrialRow};
use engine::views::{
    self, Attribution, BandRow, ExploreReply, GrowthRow, JoinedHolding, SectorShare, SectorSpread, SectorWeight, Selection,
    StatisticRow,
};
use market_data::Error;
use serde::Serialize;
use std::collections::BTreeMap;
use ts_rs::TS;

pub(crate) fn routes() -> Router<App> {
    Router::new()
        .route("/api/runs/{id}/trials", get(trials))
        .route("/api/runs/{id}/periods", get(periods))
        .route("/api/runs/{id}/holdings", get(holdings))
        .route("/api/runs/{id}/curve", get(curve))
        .route("/api/runs/{id}/sectors", get(sectors))
        .route("/api/runs/{id}/contributions", get(contributions))
        .route("/api/runs/{id}/explore", get(explore))
}

/// The statistics over the trials and each trial's summary.
#[derive(Debug, Serialize, TS)]
#[ts(export)]
pub struct TrialsReply {
    pub statistics: Vec<StatisticRow>,
    pub trials: Vec<TrialRow>,
}

/// The holdings of one trial, or of one period of it, with their step rows.
#[derive(Debug, Serialize, TS)]
#[ts(export)]
pub struct HoldingsReply {
    /// The names of the holdings' `source:` fields, in the strategy's order.
    pub sources: Vec<String>,
    pub holdings: Vec<JoinedHolding>,
    pub steps: Vec<StepRow>,
}

/// The band over the trials, or one trial's growth.
#[derive(Debug, Serialize, TS)]
#[serde(rename_all = "lowercase")]
#[ts(export)]
pub enum CurveReply {
    Band(Vec<BandRow>),
    Growth(Vec<GrowthRow>),
}

/// Each trial's sector shares and the spread over all trials, or one
/// trial's `weights`: each period's weight of each sector it holds.
#[derive(Debug, Serialize, TS)]
#[serde(untagged)]
#[ts(export)]
pub enum SectorsReply {
    All { trials: Vec<SectorShare>, spread: Vec<SectorSpread> },
    Trial { weights: Vec<SectorWeight> },
}

type Reply<T> = Result<Json<T>, Failure>;
type Values = Result<Query<BTreeMap<String, String>>, QueryRejection>;

async fn trials(State(app): State<App>, Id(id): Id) -> Reply<TrialsReply> {
    read(app, id, None, |file| Ok(TrialsReply { statistics: views::statistics(&file)?, trials: file.trials()? })).await
}

async fn periods(State(app): State<App>, Id(id): Id, query: Values) -> Reply<Vec<PeriodRow>> {
    let trial = number(&query?.0, "trial")?;
    read(app, id, Some(trial), |file| file.periods()).await
}

async fn holdings(State(app): State<App>, Id(id): Id, query: Values) -> Reply<HoldingsReply> {
    let Query(query) = query?;
    let (trial, period) = (number(&query, "trial")?, optional(&query, "period")?);
    read(app, id, Some(trial), move |file| {
        let periods = file.periods()?.len() as u32;
        if period.is_some_and(|p| p > periods) {
            return Err(Error::new(format!("trial {trial} has {periods} periods"), "period"));
        }
        let chosen = |p: u32| period.is_none_or(|n| n == p);
        let (sources, holdings) = views::holdings(&file)?;
        Ok(HoldingsReply {
            sources,
            holdings: holdings.into_iter().filter(|h| chosen(h.row.period)).collect(),
            steps: file.steps()?.into_iter().filter(|s| chosen(s.period)).collect(),
        })
    })
    .await
}

async fn curve(State(app): State<App>, Id(id): Id, query: Values) -> Reply<CurveReply> {
    let trial = optional(&query?.0, "trial")?;
    read(app, id, trial, move |file| {
        let mut growth = views::growth(&file)?;
        Ok(match trial {
            None => CurveReply::Band(views::band(&growth)),
            Some(_) => CurveReply::Growth(growth.swap_remove(0)),
        })
    })
    .await
}

async fn sectors(State(app): State<App>, Id(id): Id, query: Values) -> Reply<SectorsReply> {
    let trial = optional(&query?.0, "trial")?;
    read(app, id, trial, move |file| {
        Ok(match trial {
            None => {
                let trials = views::sectors(&file)?;
                SectorsReply::All { spread: views::sector_spread(&trials), trials: trials.concat() }
            }
            Some(_) => SectorsReply::Trial { weights: views::sector_weights(&file)? },
        })
    })
    .await
}

async fn contributions(State(app): State<App>, Id(id): Id, query: Values) -> Reply<Vec<Attribution>> {
    let trial = number(&query?.0, "trial")?;
    read(app, id, Some(trial), |file| views::contributions(&file)).await
}

async fn explore(State(app): State<App>, Id(id): Id, query: Values) -> Reply<ExploreReply> {
    let Query(query) = query?;
    let trial = match value(&query, "trial")? {
        "all" => None,
        _ => Some(number(&query, "trial")?),
    };
    let range = |name| views::range(value(&query, name)?, name).map_err(Failure::input);
    let selection = Selection { trial, periods: range("periods")?, ranks: range("ranks")? };
    read(app, id, None, move |file| views::explore(&file, &selection)).await
}

/// Opens run `id`'s result file, limited to `trial` when one is given, and
/// answers `view` of it, on a blocking thread. Every result route opens its
/// file here. A view's error is the query's (such as a trial the result
/// does not have).
async fn read<T: Send + 'static>(
    app: App,
    id: i64,
    trial: Option<u32>,
    view: impl FnOnce(ResultFile) -> Result<T, Error> + Send + 'static,
) -> Reply<T> {
    blocking(move || {
        let path = app.store.result(id)?;
        let file = ResultFile::open(&path).map_err(Failure::io)?;
        let file = match trial {
            Some(trial) => file.only(trial)?,
            None => file,
        };
        Ok(view(file)?)
    })
    .await
    .map(Json)
}

impl From<QueryRejection> for Failure {
    fn from(rejection: QueryRejection) -> Failure {
        Failure::input(Error::new(rejection.body_text(), "query"))
    }
}

fn value<'q>(query: &'q BTreeMap<String, String>, name: &str) -> Result<&'q str, Failure> {
    query.get(name).map(String::as_str).ok_or_else(|| Failure::input(Error::new(format!("give the {name}"), name)))
}

/// A count from 1.
fn number(query: &BTreeMap<String, String>, name: &str) -> Result<u32, Failure> {
    let text = value(query, name)?;
    match text.parse::<u32>() {
        Ok(n) if n >= 1 => Ok(n),
        _ => Err(Failure::input(Error::new(format!("{text:?} is not a count from 1"), name))),
    }
}

fn optional(query: &BTreeMap<String, String>, name: &str) -> Result<Option<u32>, Failure> {
    if query.contains_key(name) { number(query, name).map(Some) } else { Ok(None) }
}
