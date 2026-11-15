//! The run list and the queue over HTTP. Each route is one change of the
//! store (see the crate comment's states); the settings of a run are checked
//! here, at the input boundary, before they are stored.

use crate::http::{App, Body, Failure, Id, blocking};
use crate::store::{Edit, RunRow, RunsReply};
use axum::extract::State;
use axum::routing::{get, post, put};
use axum::{Json, Router};
use engine::commands::check_run;
use engine::{Schedule, StrategyFile};
use market_data::{Market, MarketData};
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;
use ts_rs::TS;

/// `POST /api/runs`.
#[derive(Debug, Deserialize, TS)]
#[serde(deny_unknown_fields)]
#[ts(export)]
pub struct AddRun {
    pub name: String,
    pub market: Market,
    /// A missing seed of random trials is drawn when the run is added.
    pub schedule: Schedule,
    /// A strategy file's JSON, which is read as `bt` reads the file.
    #[ts(as = "StrategyFile<'static>")]
    pub strategy: Box<RawValue>,
}

/// `PATCH /api/runs/{id}`: the fields to change. A market, schedule or
/// strategy changes a waiting or held run's settings, which are checked
/// again together.
#[derive(Debug, Deserialize, TS)]
#[serde(deny_unknown_fields)]
#[ts(export)]
pub struct EditRun {
    #[ts(optional)]
    pub name: Option<String>,
    #[ts(optional)]
    pub locked: Option<bool>,
    #[ts(optional)]
    pub market: Option<Market>,
    #[ts(optional)]
    pub schedule: Option<Schedule>,
    #[ts(as = "Option<StrategyFile<'static>>", optional)]
    pub strategy: Option<Box<RawValue>>,
}

/// `POST /api/runs/{id}/move`.
#[derive(Debug, Deserialize, TS)]
#[serde(deny_unknown_fields)]
#[ts(export)]
pub struct MoveRun {
    /// The place in the queue of waiting and held runs, from 1.
    pub to: u32,
}

/// `PUT /api/queue`, and its reply.
#[derive(Debug, Deserialize, Serialize, TS)]
#[serde(deny_unknown_fields)]
#[ts(export)]
pub struct Queue {
    pub paused: bool,
}

/// `DELETE /api/runs/{id}`'s reply: an empty object.
#[derive(Debug, Serialize, TS)]
#[ts(export)]
pub struct Deleted {}

pub(crate) fn routes() -> Router<App> {
    Router::new()
        .route("/api/runs", get(list).post(add))
        .route("/api/runs/{id}", get(one).patch(edit).delete(delete))
        .route("/api/runs/{id}/hold", post(hold))
        .route("/api/runs/{id}/release", post(release))
        .route("/api/runs/{id}/stop", post(stop))
        .route("/api/runs/{id}/move", post(move_to))
        .route("/api/queue", put(queue))
}

async fn list(State(app): State<App>) -> Result<Json<RunsReply>, Failure> {
    blocking(move || app.store.list()).await.map(Json)
}

async fn one(State(app): State<App>, Id(id): Id) -> Result<Json<RunRow>, Failure> {
    blocking(move || app.store.get(id)).await.map(Json)
}

async fn add(State(app): State<App>, Body(run): Body<AddRun>) -> Result<Json<RunRow>, Failure> {
    blocking(move || {
        let (schedule, strategy) = settings(&app, run.market, &run.schedule, run.strategy.get())?;
        let row = app.store.add(&run.name, run.market, &schedule, &strategy)?;
        app.worker.wake();
        Ok(row)
    })
    .await
    .map(Json)
}

async fn edit(State(app): State<App>, Id(id): Id, Body(edit): Body<EditRun>) -> Result<Json<RunRow>, Failure> {
    blocking(move || {
        let settings = if edit.market.is_some() || edit.schedule.is_some() || edit.strategy.is_some() {
            let stored = app.store.get(id)?;
            let market = edit.market.unwrap_or(stored.market);
            let schedule = edit.schedule.unwrap_or(stored.schedule);
            let strategy = edit.strategy.or(stored.strategy).expect("one run has its strategy");
            let (schedule, strategy) = settings(&app, market, &schedule, strategy.get())?;
            Some((market, schedule, strategy))
        } else {
            None
        };
        app.store.edit(id, &Edit { name: edit.name, locked: edit.locked, settings })
    })
    .await
    .map(Json)
}

/// Checks a run's settings against the market's data, as the run will:
/// gives the schedule with its seed drawn and the canonical strategy.
fn settings(app: &App, market: Market, schedule: &Schedule, strategy: &str) -> Result<(Schedule, String), Failure> {
    let strategy = crate::strategy(strategy)?;
    let schedule = schedule.drawn();
    let data = MarketData::open(&app.home, market)?;
    check_run(&data, "strategy", &strategy, &schedule)?;
    Ok((schedule, strategy.canonical().to_string()))
}

async fn delete(State(app): State<App>, Id(id): Id) -> Result<Json<Deleted>, Failure> {
    blocking(move || {
        app.store.delete(id)?;
        app.worker.stop(id);
        Ok(Deleted {})
    })
    .await
    .map(Json)
}

async fn hold(State(app): State<App>, Id(id): Id) -> Result<Json<RunRow>, Failure> {
    blocking(move || app.store.hold(id)).await.map(Json)
}

async fn release(State(app): State<App>, Id(id): Id) -> Result<Json<RunRow>, Failure> {
    blocking(move || {
        let row = app.store.release(id)?;
        app.worker.wake();
        Ok(row)
    })
    .await
    .map(Json)
}

async fn stop(State(app): State<App>, Id(id): Id) -> Result<Json<RunRow>, Failure> {
    blocking(move || {
        let row = app.store.stop(id)?;
        app.worker.stop(id);
        Ok(row)
    })
    .await
    .map(Json)
}

async fn move_to(State(app): State<App>, Id(id): Id, Body(place): Body<MoveRun>) -> Result<Json<RunRow>, Failure> {
    blocking(move || {
        let row = app.store.move_to(id, place.to)?;
        app.worker.wake();
        Ok(row)
    })
    .await
    .map(Json)
}

async fn queue(State(app): State<App>, Body(queue): Body<Queue>) -> Result<Json<Queue>, Failure> {
    blocking(move || {
        app.store.pause(queue.paused)?;
        app.worker.wake();
        Ok(queue)
    })
    .await
    .map(Json)
}
