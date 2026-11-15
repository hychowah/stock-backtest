//! `POST /api/formula`: the formula editor's check.
//!
//! The request is `{"formula": TEXT, "display"?: DISPLAY, "variables":
//! {NAME: {"formula": TEXT, "display"?: DISPLAY}}}`, the variables as a
//! strategy file spells them, so the formula can name them. The reply is
//! always 200 with one of two shapes, so the page draws from either:
//!
//! - `{"checked": {canonical, unit, display, displays, picture}}`: the
//!   canonical text, the unit's id, the display given (the unit's default
//!   when it is none of the unit's), the displays the unit allows, and the
//!   [`Picture`] the page draws.
//! - `{"fault": {code, message, start, end, suggestions}}`: the characters
//!   `[start, end)` at fault, counted from 0, and up to three replacements
//!   for them.
//!
//! A body that is not that JSON, or variables a strategy file would refuse,
//! get 400.

use crate::http::{App, Body, Failure, blocking};
use axum::routing::post;
use axum::{Json, Router};
use engine::{Fault, Formula, Picture, Strategy};
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;
use ts_rs::TS;

pub(crate) fn routes() -> Router<App> {
    Router::new().route("/api/formula", post(check))
}

#[derive(Deserialize, TS)]
#[serde(deny_unknown_fields)]
#[ts(export)]
pub struct FormulaRequest {
    pub formula: String,
    #[ts(optional)]
    pub display: Option<String>,
    /// In file order: a variable can name the ones before it.
    #[ts(type = "Record<string, { formula: string, display?: string }>")]
    pub variables: Box<RawValue>,
}

#[derive(Serialize, TS)]
#[serde(rename_all = "lowercase")]
#[ts(export)]
pub enum FormulaReply {
    Checked(Checked),
    Fault(Fault),
}

#[derive(Serialize, TS)]
#[ts(export)]
pub struct Checked {
    pub canonical: String,
    pub unit: &'static str,
    pub display: &'static str,
    pub displays: Vec<&'static str>,
    pub picture: Picture,
}

async fn check(Body(request): Body<FormulaRequest>) -> Result<Json<FormulaReply>, Failure> {
    blocking(move || {
        // The file's own reader checks the variables and keeps their order;
        // the strategy around them only has to be a valid one.
        let file = format!(
            r#"{{"variables": {}, "sleeves": [{{"steps": [{{"rank": "Revenue", "order": "highest", "from": 1, "to": 1}}]}}]}}"#,
            request.variables.get()
        );
        let strategy = Strategy::parse(&file)?;
        Ok(Json(match Formula::read(&request.formula, strategy.variables()) {
            Err(fault) => FormulaReply::Fault(fault),
            Ok(formula) => {
                let unit = formula.unit();
                let display = request.display.as_deref().and_then(|d| unit.displays().iter().copied().find(|&shown| shown == d));
                FormulaReply::Checked(Checked {
                    canonical: formula.text().to_string(),
                    unit: unit.id(),
                    display: display.unwrap_or(formula.display()),
                    displays: unit.displays().to_vec(),
                    picture: formula.picture(),
                })
            }
        }))
    })
    .await
}
