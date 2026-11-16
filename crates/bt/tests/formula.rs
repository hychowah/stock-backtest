//! `POST /api/formula`: the editor's check of a formula.

mod common;

use common::{prepared, serve};
use serde_json::json;

#[test]
fn the_formula_route_checks_draws_and_refuses_a_formula() {
    let dir = tempfile::tempdir().unwrap();
    let server = serve(&prepared(dir.path()));
    let post = |body| server.send("POST", "/api/formula", Some(&body), None);

    let (status, reply) = post(json!({"formula": "Share price / ago(Share price, 3 months) - 1", "variables": {}}));
    let fraction = json!({"op": "/", "positive": false, "top": {"name": "Share price"}, "bottom": {
        "fn": "ago", "hint": "value 3 months earlier",
        "args": [{"name": "Share price"}, {"number": "3", "unit": "months"}]}});
    let picture = json!({"op": "-", "left": fraction, "right": {"number": "1", "unit": null}});
    let displays = json!(["number", "multiple", "percent", "percentage_points"]);
    let checked = json!({"canonical": "Share price / ago(Share price, 3 months) - 1", "unit": "scalar", "display": "percent",
        "displays": displays, "picture": picture});
    assert_eq!((status, reply), (200, json!({"checked": checked})));

    // An earlier variable can be named; the display given is kept when the unit allows it.
    let variables = json!({"Debt to EV": {"formula": "Total debt / positive(Enterprise value)", "display": "multiple"}});
    let (status, reply) = post(json!({"formula": "debt to ev * 2", "display": "multiple", "variables": variables}));
    let picture = json!({"op": "*", "left": {"name": "Debt to EV"}, "right": {"number": "2", "unit": null}});
    let checked = json!({"canonical": "Debt to EV * 2", "unit": "scalar", "display": "multiple", "displays": displays, "picture": picture});
    assert_eq!((status, reply), (200, json!({"checked": checked})));

    // A refused formula is still a 200: its code, its characters and what to type instead.
    let (status, reply) = post(json!({"formula": "Revenu * 2", "variables": {}}));
    let fault = json!({"code": "UNKNOWN_NAME", "message": "“Revenu” is not a known name or a variable of this file.", "start": 0, "end": 6,
        "suggestions": [{"text": "Revenue", "label": "Revenue"}]});
    assert_eq!((status, reply), (200, json!({"fault": fault})));

    for body in [json!({"formula": 5, "variables": {}}), json!({"formula": "Revenue", "dispaly": "number", "variables": {}}), json!({"formula": "Revenue"}), json!({"formula": "Revenue", "variables": []})] {
        let (status, reply) = post(body);
        assert_eq!((status, &reply["error"]["place"].is_string()), (400, &true), "{reply}");
    }
}
