//! The prepared store: per market, immutable generations of named, typed
//! column files that readers map into memory. It knows nothing about any kind
//! of market data; each kind names its own columns.
//!
//! # Layout
//!
//! Under the runtime folder ([`Home`]):
//!
//! - `data/prepared/prepare.lock` is the preparation lock ([`Lock`]).
//! - `data/prepared/<market>/current` holds the number of the published
//!   generation, as decimal text.
//! - `data/prepared/<market>/<n>/` is generation n. n counts up per market.
//!
//! A generation folder holds `manifest.json` and one file per column. The file
//! name is the column name, by convention `<group>.<name>` (`prices.close`).
//! A column file is its values back to back, little-endian, with no header:
//!
//! | Kind | Type |
//! |---|---|
//! | days ([`Day`], days since 1970-01-01) | `i32` |
//! | values | `f64` |
//! | reasons (0 is a valid reason) | `u8` |
//! | counts | `u32` |
//! | per-company offsets | `u64` |
//!
//! A text column `<name>` is two columns: `<name>.bytes` (`u8`, the UTF-8
//! texts back to back) and `<name>.offsets` (`u64`, one more entry than
//! texts; text i is `bytes[offsets[i]..offsets[i + 1]]`).
//!
//! `manifest.json` ([`Manifest`]) holds `format` ([`FORMAT`]), `market`,
//! `generation`, `as_of`, `program`, `build_seconds`, and the `type` and
//! `length` (in values) of each column.
//!
//! # Publish rules
//!
//! 1. A preparation takes the lock ([`Lock::take`]) and fails if another
//!    preparation holds it. Readers take no lock.
//! 2. [`Lock::begin`] deletes the market's generations except `current`,
//!    then creates the next generation's folder.
//! 3. The build writes the columns ([`GenerationWriter::column`],
//!    [`GenerationWriter::text`]); each file is fsynced.
//! 4. [`GenerationWriter::publish`] writes the manifest, fsyncs it and the
//!    folder, then renames `current.tmp` over `current`.
//!
//! A published generation never changes. The generation it replaced stays on
//! disk until the next preparation, so a reader that has just read `current`
//! still finds its files. A reader that has mapped a generation keeps reading
//! it after it is deleted, because Linux keeps a mapped file alive. A failed
//! build leaves its folder, which the next preparation deletes; `current`
//! stays as it was. At most two generations per market are on disk.
//!
//! The store is derived data: a change of layout raises [`FORMAT`], and
//! [`Generation::open`] then asks for a new preparation. There is no migration.

use crate::commands::Home;
use crate::{Day, Error, Market, PROGRAM};
use chrono::{DateTime, FixedOffset};
use memmap2::Mmap;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap};
use std::fs::{self, File};
use std::io::{self, BufWriter, Write};
use std::marker::PhantomData;
use std::path::{Path, PathBuf};

#[cfg(not(target_endian = "little"))]
compile_error!("the prepared store maps little-endian column files as native values");

/// The layout version this program writes and reads. Raise it whenever the
/// meaning, type or name of any column changes.
pub const FORMAT: u32 = 2;

/// A type a column holds: plain values for which every bit pattern is valid.
/// Implemented for `i32`, [`Day`], `f64`, `u8`, `u32` and `u64` only.
pub trait Element: Copy + sealed::Sealed + 'static {
    /// The type's name in the manifest. [`Day`] columns are `i32`.
    const TYPE: &'static str;
}

mod sealed {
    pub trait Sealed {
        fn write_le(self, out: &mut impl std::io::Write) -> std::io::Result<()>;
    }
}

macro_rules! element {
    ($($t:ty),*) => {$(
        impl Element for $t {
            const TYPE: &'static str = stringify!($t);
        }
        impl sealed::Sealed for $t {
            fn write_le(self, out: &mut impl Write) -> io::Result<()> {
                out.write_all(&self.to_le_bytes())
            }
        }
    )*};
}
element!(i32, f64, u8, u32, u64);

impl Element for Day {
    const TYPE: &'static str = "i32";
}
impl sealed::Sealed for Day {
    fn write_le(self, out: &mut impl Write) -> io::Result<()> {
        self.0.write_le(out)
    }
}

fn type_size(name: &str) -> u64 {
    match name {
        "u8" => 1,
        "i32" | "u32" => 4,
        "f64" | "u64" => 8,
        _ => panic!("unknown column type {name} in a manifest of format {FORMAT}"),
    }
}

/// The record of one generation, `manifest.json`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Manifest {
    pub format: u32,
    pub market: Market,
    pub generation: u64,
    /// The preparation's as-of time, RFC 3339.
    pub as_of: String,
    /// The program and version that wrote it, such as `bt 0.1.0`.
    pub program: String,
    pub build_seconds: f64,
    /// Every column by name.
    pub columns: BTreeMap<String, ColumnInfo>,
}

impl Manifest {
    /// The size of all column files.
    pub(crate) fn bytes(&self) -> u64 {
        self.columns.values().map(|c| c.length * type_size(&c.kind)).sum()
    }
}

/// One column's entry in the manifest.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ColumnInfo {
    /// [`Element::TYPE`] of its values.
    #[serde(rename = "type")]
    pub kind: String,
    /// The number of values.
    pub length: u64,
}

/// The preparation lock. While a `Lock` lives, no other preparation can take
/// it; the operating system releases it when the value is dropped or the
/// process ends, so a crash leaves no stale lock.
pub struct Lock {
    _file: File,
    prepared: PathBuf,
}

impl Lock {
    /// Takes the lock without waiting. Fails when another preparation holds it.
    pub fn take(home: &Home) -> Result<Lock, Error> {
        let prepared = home.prepared();
        let path = prepared.join("prepare.lock");
        fs::create_dir_all(&prepared).map_err(|e| io_error("cannot create the folder", &prepared, e))?;
        let file = File::options()
            .create(true)
            .truncate(false)
            .write(true)
            .open(&path)
            .map_err(|e| io_error("cannot open the lock", &path, e))?;
        match file.try_lock() {
            Ok(()) => Ok(Lock { _file: file, prepared }),
            Err(fs::TryLockError::WouldBlock) => Err(Error::new("another preparation is running", path.display())),
            Err(fs::TryLockError::Error(e)) => Err(io_error("cannot take the lock", &path, e)),
        }
    }

    /// Starts the next generation of `market`: deletes the market's
    /// generations except `current` (old ones and failed builds), then
    /// creates an empty folder numbered one above any seen.
    pub fn begin(&self, market: Market) -> Result<GenerationWriter<'_>, Error> {
        let dir = self.prepared.join(market.id());
        fs::create_dir_all(&dir).map_err(|e| io_error("cannot create the folder", &dir, e))?;
        let current = read_current(&dir)?;
        let mut last = 0;
        let entries = fs::read_dir(&dir).map_err(|e| io_error("cannot list the folder", &dir, e))?;
        for entry in entries {
            let entry = entry.map_err(|e| io_error("cannot list the folder", &dir, e))?;
            let Some(n) = entry.file_name().to_str().and_then(|name| name.parse::<u64>().ok()) else {
                continue;
            };
            last = last.max(n);
            if Some(n) != current {
                let path = entry.path();
                fs::remove_dir_all(&path).map_err(|e| io_error("cannot delete an old generation", &path, e))?;
            }
        }
        let generation = last + 1;
        let folder = dir.join(generation.to_string());
        fs::create_dir(&folder).map_err(|e| io_error("cannot create the folder", &folder, e))?;
        Ok(GenerationWriter { _lock: PhantomData, market, generation, dir, folder, columns: BTreeMap::new() })
    }
}

/// A generation being built. Write each column once; nothing is visible to
/// readers until [`publish`](Self::publish). Dropping it without publishing
/// leaves an unpublished folder that the next preparation deletes.
pub struct GenerationWriter<'lock> {
    _lock: PhantomData<&'lock Lock>,
    market: Market,
    generation: u64,
    dir: PathBuf,
    folder: PathBuf,
    columns: BTreeMap<String, ColumnInfo>,
}

impl GenerationWriter<'_> {
    /// Writes column `name` (`<group>.<name>`), with `values` in order. The
    /// reader gets them back as a slice from [`Generation::column`].
    pub fn column<T: Element>(&mut self, name: &str, values: &[T]) -> Result<(), Error> {
        let path = self.folder.join(name);
        let write = || -> io::Result<()> {
            let mut out = BufWriter::new(File::create(&path)?);
            for &value in values {
                value.write_le(&mut out)?;
            }
            out.into_inner().map_err(io::IntoInnerError::into_error)?.sync_all()
        };
        write().map_err(|e| io_error("cannot write the column", &path, e))?;
        self.columns.insert(name.to_string(), ColumnInfo { kind: T::TYPE.to_string(), length: values.len() as u64 });
        Ok(())
    }

    /// Writes text column `name`: the columns `<name>.bytes` and
    /// `<name>.offsets`. The reader gets them back from [`Generation::text`].
    pub fn text<S: AsRef<str>>(&mut self, name: &str, values: &[S]) -> Result<(), Error> {
        let mut bytes = Vec::new();
        let mut offsets = Vec::with_capacity(values.len() + 1);
        offsets.push(0u64);
        for value in values {
            bytes.extend_from_slice(value.as_ref().as_bytes());
            offsets.push(bytes.len() as u64);
        }
        self.column(&format!("{name}.bytes"), &bytes)?;
        self.column(&format!("{name}.offsets"), &offsets)
    }

    /// Writes the manifest and makes this generation the market's `current`.
    /// Returns the manifest written.
    pub fn publish(self, as_of: &DateTime<FixedOffset>, build_seconds: f64) -> Result<Manifest, Error> {
        let manifest = Manifest {
            format: FORMAT,
            market: self.market,
            generation: self.generation,
            as_of: as_of.to_rfc3339(),
            program: PROGRAM.to_string(),
            build_seconds,
            columns: self.columns,
        };
        let text = serde_json::to_string_pretty(&manifest).expect("a manifest is JSON") + "\n";
        write_synced(&self.folder.join("manifest.json"), text.as_bytes())?;
        sync_folder(&self.folder)?;
        let (tmp, current) = (self.dir.join("current.tmp"), self.dir.join("current"));
        write_synced(&tmp, format!("{}\n", self.generation).as_bytes())?;
        fs::rename(&tmp, &current).map_err(|e| io_error("cannot publish", &current, e))?;
        sync_folder(&self.dir)?;
        Ok(manifest)
    }
}

/// One opened generation: its manifest and its columns, mapped. It reads the
/// generation `current` named at open, unchanged until dropped, even after a
/// later preparation publishes another or deletes it.
pub struct Generation {
    manifest: Manifest,
    maps: HashMap<String, Mmap>,
}

impl Generation {
    /// Maps the current generation of `market`. Fails, asking to run
    /// `bt data prepare`, when the market has no `current` or its manifest has
    /// another [`FORMAT`]; fails, naming the column, when a column file's size
    /// differs from its manifest entry. Reads after open trust the store.
    pub fn open(home: &Home, market: Market) -> Result<Generation, Error> {
        let dir = home.prepared().join(market.id());
        let Some(generation) = read_current(&dir)? else {
            let message = format!("{} is not prepared: run `bt data prepare`", market.id());
            return Err(Error::new(message, dir.join("current").display()));
        };
        let folder = dir.join(generation.to_string());
        let path = folder.join("manifest.json");
        let text = fs::read_to_string(&path).map_err(|e| io_error("cannot read the manifest", &path, e))?;
        #[derive(Deserialize)]
        struct Format {
            format: u32,
        }
        let format = serde_json::from_str::<Format>(&text).map(|f| f.format).ok();
        if format != Some(FORMAT) {
            let message = format!("the prepared data has another format than this program reads ({FORMAT}): run `bt data prepare`");
            return Err(Error::new(message, path.display()));
        }
        let manifest: Manifest =
            serde_json::from_str(&text).map_err(|e| Error::new(format!("unreadable manifest: {e}"), path.display()))?;
        let mut maps = HashMap::with_capacity(manifest.columns.len());
        for (name, column) in &manifest.columns {
            let path = folder.join(name);
            let file = File::open(&path).map_err(|e| io_error("cannot open the column", &path, e))?;
            // SAFETY: a published generation's files are never written again
            // (they are only deleted, which keeps a mapping valid), so the
            // mapped bytes cannot change while this value borrows them.
            let map = unsafe { Mmap::map(&file) }.map_err(|e| io_error("cannot map the column", &path, e))?;
            let expected = column.length * type_size(&column.kind);
            if map.len() as u64 != expected {
                let message = format!("column {name} has {} bytes, its manifest says {expected}", map.len());
                return Err(Error::new(message, path.display()));
            }
            maps.insert(name.clone(), map);
        }
        Ok(Generation { manifest, maps })
    }

    pub fn manifest(&self) -> &Manifest {
        &self.manifest
    }

    /// Column `name` as written by [`GenerationWriter::column`]. Panics when
    /// the generation has no such column or it holds another type: the build
    /// and the readers of one [`FORMAT`] agree on both.
    pub fn column<T: Element>(&self, name: &str) -> &[T] {
        let kind = self.manifest.columns.get(name).map(|c| c.kind.as_str());
        assert_eq!(kind, Some(T::TYPE), "column {name}");
        let bytes: &[u8] = &self.maps[name];
        // SAFETY: `Element` is sealed to plain number types for which every bit
        // pattern is a valid value; the assert below rules out misalignment.
        let (head, values, tail) = unsafe { bytes.align_to::<T>() };
        assert!(head.is_empty() && tail.is_empty(), "column {name} is not aligned");
        values
    }

    /// Text column `name` as written by [`GenerationWriter::text`].
    pub fn text(&self, name: &str) -> Text<'_> {
        Text { bytes: self.column(&format!("{name}.bytes")), offsets: self.column(&format!("{name}.offsets")) }
    }
}

/// A mapped text column: `len()` texts, read by position.
#[derive(Clone, Copy)]
pub struct Text<'a> {
    bytes: &'a [u8],
    offsets: &'a [u64],
}

impl<'a> Text<'a> {
    pub fn len(&self) -> usize {
        self.offsets.len() - 1
    }

    /// Text `i`. Panics when `i >= len()`.
    pub fn get(&self, i: usize) -> &'a str {
        let range = self.offsets[i] as usize..self.offsets[i + 1] as usize;
        std::str::from_utf8(&self.bytes[range]).expect("text columns hold UTF-8")
    }
}

/// The generation number in `<dir>/current`, or `None` when there is none.
fn read_current(dir: &Path) -> Result<Option<u64>, Error> {
    let path = dir.join("current");
    match fs::read_to_string(&path) {
        Ok(text) => text
            .trim()
            .parse()
            .map(Some)
            .map_err(|_| Error::new("not a generation number: run `bt data prepare`", path.display())),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(io_error("cannot read", &path, e)),
    }
}

fn write_synced(path: &Path, bytes: &[u8]) -> Result<(), Error> {
    let write = || -> io::Result<()> {
        let mut file = File::create(path)?;
        file.write_all(bytes)?;
        file.sync_all()
    };
    write().map_err(|e| io_error("cannot write", path, e))
}

fn sync_folder(dir: &Path) -> Result<(), Error> {
    File::open(dir).and_then(|f| f.sync_all()).map_err(|e| io_error("cannot sync the folder", dir, e))
}

fn io_error(what: &str, path: &Path, error: io::Error) -> Error {
    Error::new(format!("{what}: {error}"), path.display())
}
