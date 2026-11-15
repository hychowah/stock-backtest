//! The variable library: named formulas that the formula editor offers and
//! copies into strategy files.
//!
//! The entries are read as one strategy file's `variables`, in dependency
//! order: an entry comes after the entries it names, ties by id. So an older
//! entry may name a newer one. Every change is checked by reading the
//! changed library with the engine's own variables reader, inside the
//! transaction that writes it, so the stored library always reads.
//!
//! A change is refused with 409 when it gives two entries one name (as
//! names compare: case and spacing aside), makes entries name each other in
//! a cycle, or deletes or renames an entry that another uses; and with 400
//! when the formula or display does not read.

use crate::http::{App, Body, Failure, Id, blocking};
use crate::store::missing;
use axum::extract::State;
use axum::routing::{get, put};
use axum::{Json, Router};
use engine::names::{self, Display};
use engine::{Formula, Strategy};
use market_data::Error;
use rusqlite::Transaction;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use ts_rs::TS;

/// An entry of the library.
#[derive(Debug, Serialize, TS)]
#[ts(export)]
pub struct Variable {
    pub id: i64,
    pub name: String,
    /// The canonical formula text.
    pub formula: String,
    pub display: Display,
    pub favourite: bool,
    /// The entries its formula names, directly or through others, in
    /// library order: what a strategy file needs beside it.
    pub uses: Vec<String>,
}

/// `POST /api/variables` and `PUT /api/variables/{id}`: the whole entry.
#[derive(Debug, Deserialize, TS)]
#[serde(deny_unknown_fields)]
#[ts(export)]
pub struct NewVariable {
    pub name: String,
    pub formula: String,
    /// The unit's default display when absent.
    #[ts(optional)]
    pub display: Option<String>,
    pub favourite: bool,
}

/// One stored entry.
#[derive(Clone, Debug)]
struct Row {
    id: i64,
    name: String,
    formula: String,
    display: Option<String>,
    favourite: bool,
}

/// The library as it reads: the rows in dependency order, each with its
/// formula (named, in its display).
struct Library {
    rows: Vec<Row>,
    formulas: Vec<Arc<Formula>>,
}

pub(crate) fn routes() -> Router<App> {
    Router::new()
        .route("/api/variables", get(list).post(add))
        .route("/api/variables/{id}", put(replace).delete(delete))
}

async fn list(State(app): State<App>) -> Result<Json<Vec<Variable>>, Failure> {
    blocking(move || {
        let mut db = app.store.connect()?;
        Ok(stored(&db.transaction()?)?.entries())
    })
    .await
    .map(Json)
}

async fn add(State(app): State<App>, Body(entry): Body<NewVariable>) -> Result<Json<Variable>, Failure> {
    blocking(move || {
        change(&app, |tx, now| {
            // A new entry's id is above every other's.
            let (library, at) = now.with(row(i64::MAX, entry))?;
            let (row, formula) = (&library.rows[at], &library.formulas[at]);
            let sql = "INSERT INTO variables(name, formula, display, favourite) VALUES(?, ?, ?, ?) RETURNING id";
            let id = tx.query_row(sql, (&row.name, formula.text(), formula.display(), row.favourite), |r| r.get(0))?;
            Ok(Variable { id, ..library.entry(at) })
        })
    })
    .await
    .map(Json)
}

async fn replace(State(app): State<App>, Id(id): Id, Body(entry): Body<NewVariable>) -> Result<Json<Variable>, Failure> {
    blocking(move || {
        change(&app, |tx, now| {
            let old = now.find(id)?;
            if names::key(&entry.name) != names::key(&old.name) {
                now.unused(old)?;
            }
            let (library, at) = now.with(row(id, entry))?;
            let (row, formula) = (&library.rows[at], &library.formulas[at]);
            let sql = "UPDATE variables SET name=?, formula=?, display=?, favourite=? WHERE id=?";
            tx.execute(sql, (&row.name, formula.text(), formula.display(), row.favourite, id))?;
            Ok(library.entry(at))
        })
    })
    .await
    .map(Json)
}

async fn delete(State(app): State<App>, Id(id): Id) -> Result<Json<crate::Deleted>, Failure> {
    blocking(move || {
        change(&app, |tx, now| {
            now.unused(now.find(id)?)?;
            tx.execute("DELETE FROM variables WHERE id=?", [id])?;
            Ok(crate::Deleted {})
        })
    })
    .await
    .map(Json)
}

fn row(id: i64, entry: NewVariable) -> Row {
    Row { id, name: entry.name.trim().to_string(), formula: entry.formula, display: entry.display, favourite: entry.favourite }
}

/// Runs one change in a write transaction, with the stored library.
fn change<T>(app: &App, work: impl FnOnce(&Transaction<'_>, &Library) -> Result<T, Failure>) -> Result<T, Failure> {
    let mut db = app.store.connect()?;
    let tx = db.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    let now = stored(&tx)?;
    let done = work(&tx, &now)?;
    tx.commit()?;
    Ok(done)
}

/// The stored library, which always reads.
fn stored(tx: &Transaction<'_>) -> Result<Library, Failure> {
    let rows = tx
        .prepare("SELECT id, name, formula, display, favourite FROM variables")?
        .query_map([], |row| {
            Ok(Row { id: row.get(0)?, name: row.get(1)?, formula: row.get(2)?, display: Some(row.get(3)?), favourite: row.get(4)? })
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    let unread = || Failure::io(Error::new("the stored variable library does not read", "data/app.sqlite"));
    let rows = order(rows).map_err(|_| unread())?;
    let formulas = Strategy::read_variables(&variables(&rows)).map_err(|_| unread())?;
    Ok(Library { rows, formulas })
}

/// Why the rows cannot be put in dependency order.
enum Unordered {
    /// Each row left names a variable that is not placed: the rows left.
    Waiting(Vec<Row>),
    /// A row's formula has a fault of its own once the names it reads are
    /// placed, such as units that no longer fit: that fault, placed as the
    /// variables reader places it.
    Fault(Error),
}

/// The rows in dependency order: in id order, each time the first row whose
/// formula reads with the rows placed before it.
fn order(mut rows: Vec<Row>) -> Result<Vec<Row>, Unordered> {
    rows.sort_by_key(|row| row.id);
    let (mut placed, mut formulas) = (Vec::new(), Vec::new());
    while !rows.is_empty() {
        let mut own = None;
        let next = rows.iter().position(|row| match Formula::read(&row.formula, &formulas) {
            Ok(formula) => {
                formulas.push(Arc::new(formula.named(&row.name)));
                true
            }
            Err(fault) => {
                if fault.code != "UNKNOWN_NAME" && own.is_none() {
                    own = Some(Error::new(fault.sentence(), format!("variables.{:?}, {}", row.name, fault.place())));
                }
                false
            }
        });
        match (next, own) {
            (Some(i), _) => placed.push(rows.remove(i)),
            (None, Some(fault)) => return Err(Unordered::Fault(fault)),
            (None, None) => return Err(Unordered::Waiting(rows)),
        }
    }
    Ok(placed)
}

/// The rows as the `variables` object of a strategy file, in their order.
fn variables(rows: &[Row]) -> String {
    let entries: Vec<String> = rows
        .iter()
        .map(|row| {
            let mut fields = serde_json::json!({ "formula": row.formula });
            if let Some(display) = &row.display {
                fields["display"] = display.as_str().into();
            }
            format!("{}:{fields}", serde_json::to_string(&row.name).expect("a name serializes"))
        })
        .collect();
    format!("{{{}}}", entries.join(","))
}

impl Library {
    /// The library with `changed` added, or in place of the entry with its
    /// id, checked: the formula alone first (400 for its own fault), then the
    /// dependency order (409 for a cycle), then the engine's variables reader
    /// over the whole library. Gives the place of the changed entry.
    fn with(&self, changed: Row) -> Result<(Library, usize), Failure> {
        if let Some(other) = self.rows.iter().find(|r| r.id != changed.id && names::key(&r.name) == names::key(&changed.name)) {
            return Err(Failure::conflict(Error::new(format!("the variable {:?} has this name", other.name), "name")));
        }
        Formula::read(&changed.formula, &self.formulas)
            .map_err(|fault| Failure::input(Error::new(fault.message.clone(), format!("formula, {}", fault.place()))))?;
        let id = changed.id;
        let rows = self.rows.iter().filter(|r| r.id != id).cloned().chain([changed]).collect();
        let rows = order(rows).map_err(|unordered| match unordered {
            Unordered::Fault(error) => Failure::input(error),
            Unordered::Waiting(left) => {
                let names: Vec<&str> = left.iter().map(|r| r.name.as_str()).collect();
                let message = format!(
                    "these variables name each other in a cycle, or name a variable that no longer exists: {}",
                    names.join(", ")
                );
                Failure::conflict(Error::new(message, "formula"))
            }
        })?;
        let formulas = Strategy::read_variables(&variables(&rows)).map_err(Failure::input)?;
        let at = rows.iter().position(|r| r.id == id).expect("the changed entry");
        Ok((Library { rows, formulas }, at))
    }

    fn find(&self, id: i64) -> Result<&Row, Failure> {
        self.rows.iter().find(|r| r.id == id).ok_or_else(|| missing("variable", id))
    }

    /// Refuses with 409 when another entry uses `row`.
    fn unused(&self, row: &Row) -> Result<(), Failure> {
        let users: Vec<String> = self.entries().into_iter().filter(|e| e.uses.contains(&row.name)).map(|e| e.name).collect();
        if users.is_empty() {
            return Ok(());
        }
        Err(Failure::conflict(Error::new(format!("{} uses {:?}: change it first", users.join(", "), row.name), "name")))
    }

    fn entry(&self, at: usize) -> Variable {
        let (row, formula) = (&self.rows[at], &self.formulas[at]);
        let named = formula.uses();
        let uses = self.rows.iter().map(|r| r.name.clone()).filter(|name| named.contains(&name.as_str())).collect();
        Variable {
            id: row.id,
            name: row.name.clone(),
            formula: formula.text().to_string(),
            display: Display::of(formula.display()),
            favourite: row.favourite,
            uses,
        }
    }

    fn entries(&self) -> Vec<Variable> {
        (0..self.rows.len()).map(|at| self.entry(at)).collect()
    }
}
