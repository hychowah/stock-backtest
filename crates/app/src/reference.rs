//! The routes that read the home's prepared data, with the replies of the
//! `bt` commands of the same names.

use crate::http::{App, Body, Failure, blocking};
use axum::extract::{Path, State};
use axum::routing::{get, post};
use axum::{Json, Router};
use engine::StrategyFile;
use engine::commands::{CatalogReply, ScreenReply, ScreenRequest};
use market_data::Market;
use market_data::commands::StatusReply;
use serde::Deserialize;
use serde_json::value::RawValue;
use ts_rs::TS;

pub(crate) fn routes() -> Router<App> {
    Router::new()
        .route("/api/catalog/{market}", get(catalog))
        .route("/api/screen", post(screen))
        .route("/api/data/status", get(status))
}

/// The latest picks of a strategy in a market.
#[derive(Debug, Deserialize, TS)]
#[serde(deny_unknown_fields)]
#[ts(export)]
pub struct ScreenBody {
    /// A strategy file's JSON, which is read as `bt` reads the file.
    #[ts(as = "StrategyFile<'static>")]
    pub strategy: Box<RawValue>,
    pub market: Market,
}

async fn catalog(State(app): State<App>, Path(market): Path<String>) -> Result<Json<CatalogReply>, Failure> {
    let market: Market = market.parse().map_err(Failure::unknown)?;
    blocking(move || Ok(engine::commands::catalog(&app.home, market)?)).await.map(Json)
}

async fn screen(State(app): State<App>, Body(body): Body<ScreenBody>) -> Result<Json<ScreenReply>, Failure> {
    blocking(move || {
        let strategy = crate::strategy(body.strategy.get())?;
        Ok(engine::commands::screen(&app.home, &ScreenRequest { name: "strategy".into(), strategy, market: body.market })?)
    })
    .await
    .map(Json)
}

async fn status(State(app): State<App>) -> Result<Json<StatusReply>, Failure> {
    blocking(move || Ok(market_data::commands::status(&app.home))).await.map(Json)
}
