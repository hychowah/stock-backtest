//! The formula editor's check: the formula read with the variables of the
//! file being written, answered as the editor draws it.

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

/// A formula to check, with the variables of a strategy file, as the file
/// spells them, so the formula can name them.
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

/// One of two shapes, so the page draws from either: the formula as read,
/// or the fault: the characters `[start, end)` at fault, counted from 0, and
/// up to three replacements for them.
#[derive(Serialize, TS)]
#[serde(rename_all = "lowercase")]
#[ts(export)]
pub enum FormulaReply {
    Checked(CheckedFormula),
    Fault(Fault),
}

#[derive(Serialize, TS)]
#[ts(export)]
pub struct CheckedFormula {
    pub canonical: String,
    /// The unit's id.
    pub unit: &'static str,
    /// The display given, or the unit's default when it is none of the
    /// unit's; and the displays the unit allows.
    pub display: &'static str,
    pub displays: Vec<&'static str>,
    /// What the page draws to show how the text was read.
    pub picture: Picture,
}

async fn check(Body(request): Body<FormulaRequest>) -> Result<Json<FormulaReply>, Failure> {
    blocking(move || {
        let variables = Strategy::read_variables(request.variables.get())?;
        Ok(Json(match Formula::read(&request.formula, &variables) {
            Err(fault) => FormulaReply::Fault(fault),
            Ok(formula) => {
                let unit = formula.unit();
                let display = request.display.as_deref().and_then(|d| unit.displays().iter().copied().find(|&shown| shown == d));
                FormulaReply::Checked(CheckedFormula {
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
