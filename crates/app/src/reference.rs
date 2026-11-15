//! The routes that read the home's prepared data, with the replies of the
//! `bt` commands of the same names.
//!
//! | Route | Request | Reply |
//! |---|---|---|
//! | `GET /api/catalog/{market}` | | [`CatalogReply`] (`bt catalog`) |
//! | `POST /api/screen` | [`ScreenBody`] | [`ScreenReply`] (`bt screen`) |
//! | `GET /api/data/status` | | [`StatusReply`] (`bt data status`) |
//!
//! An unknown market in the path gets 404. A strategy that does not read,
//! or that does not fit the market's data, gets 400 with the place in the
//! strategy after `strategy: `.

use crate::http::{App, Body, Failure, blocking};
use axum::extract::{Path, State};
use axum::routing::{get, post};
use axum::{Json, Router};
use engine::Strategy;
use engine::commands::{CatalogReply, CatalogRequest, ScreenReply, ScreenRequest};
use market_data::Market;
use market_data::commands::StatusReply;
use serde::Deserialize;
use ts_rs::TS;

pub(crate) fn routes() -> Router<App> {
    Router::new()
        .route("/api/catalog/{market}", get(catalog))
        .route("/api/screen", post(screen))
        .route("/api/data/status", get(status))
}

/// The latest picks of a strategy, given as the text of a strategy file.
#[derive(Debug, Deserialize, TS)]
#[ts(export)]
pub struct ScreenBody {
    pub strategy: String,
    pub market: Market,
}

async fn catalog(State(app): State<App>, Path(market): Path<String>) -> Result<Json<CatalogReply>, Failure> {
    let market: Market = market.parse().map_err(Failure::unknown)?;
    blocking(move || Ok(engine::commands::catalog(&app.home, &CatalogRequest { market })?)).await.map(Json)
}

async fn screen(State(app): State<App>, Body(body): Body<ScreenBody>) -> Result<Json<ScreenReply>, Failure> {
    blocking(move || {
        let name = "strategy".to_string();
        let strategy = Strategy::parse(&body.strategy).map_err(|e| e.in_file(&name))?;
        Ok(engine::commands::screen(&app.home, &ScreenRequest { name, strategy, market: body.market })?)
    })
    .await
    .map(Json)
}

async fn status(State(app): State<App>) -> Result<Json<StatusReply>, Failure> {
    blocking(move || Ok(market_data::commands::status(&app.home))).await.map(Json)
}
