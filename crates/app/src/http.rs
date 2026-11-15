//! The HTTP server: the routes, the error replies and the origin rule.
//!
//! `bt serve` listens on `127.0.0.1` only (remote use goes through a
//! forward to that address) and serves `<home>/web/` at `/`, beside the API.
//!
//! | Route | Request | Reply |
//! |---|---|---|
//! | `GET /api/runs` | | [`RunsReply`](crate::RunsReply): the pause and every run without its strategy |
//! | `POST /api/runs` | [`AddRun`](crate::AddRun) | the new waiting run |
//! | `GET /api/runs/{id}` | | the [`RunRow`](crate::RunRow) with its canonical strategy |
//! | `PATCH /api/runs/{id}` | [`EditRun`](crate::EditRun): name, locked, and a waiting or held run's settings | the run |
//! | `DELETE /api/runs/{id}` | | `{}`; 409 when locked; a running run is stopped |
//! | `POST /api/runs/{id}/hold`, `release`, `stop` | | the run |
//! | `POST /api/runs/{id}/move` | [`MoveRun`](crate::MoveRun) | the run |
//! | `PUT /api/queue` | [`Queue`](crate::Queue) | the same |
//! | `GET /api/variables` | | [`Variable`](crate::Variable)s in dependency order |
//! | `POST /api/variables` | [`NewVariable`](crate::NewVariable) | the new entry |
//! | `PUT /api/variables/{id}` | [`NewVariable`](crate::NewVariable) | the entry |
//! | `DELETE /api/variables/{id}` | | `{}`; 409 when another entry uses it |
//! | `POST /api/formula` | `FormulaRequest` | `FormulaReply`: `checked`, or a `fault` |
//!
//! Every reply under `/api/` is JSON. A refused request gets `{"error":
//! {"message", "place"}}` with 400 for wrong input (an id that is not a
//! number included), 403 for a change from another origin, 404 for an
//! unknown id or path, 405 for a method a route does not have, 409 for a change the run's state does not
//! allow (or that lost a race with the worker) and 500 for a failed read or
//! write of the home's files.
//!
//! The origin rule, as today's website has it: a request other than GET
//! whose `Origin` header is not `http://<Host>` gets 403. A page of another
//! site can then read nothing and change nothing, and a script that sends no
//! `Origin` is not refused.
//!
//! A handler does its work, database and engine calls alike, on a blocking
//! thread ([`blocking`]), so a slow call never holds up the server.

use crate::store::Store;
use crate::worker::Worker;
use axum::Router;
use axum::body::Bytes;
use axum::extract::{FromRequest, FromRequestParts, Request};
use axum::http::request::Parts;
use axum::http::{Method, StatusCode, header};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::any;
use axum::Json;
use market_data::Error;
use market_data::commands::Home;
use serde::de::DeserializeOwned;
use std::fs::File;
use std::net::SocketAddr;
use std::path::Path;
use tower_http::services::ServeDir;

/// What every route handler receives as its state.
#[derive(Clone, Debug)]
pub struct App {
    /// The home's prepared data and raw cache, for the engine.
    pub home: Home,
    /// `data/app.sqlite` and the result files of the runs.
    pub store: Store,
    pub(crate) worker: Worker,
}

/// A refused request: its status and the error the reply carries.
#[derive(Debug)]
pub struct Failure {
    pub status: StatusCode,
    pub error: Error,
}

impl Failure {
    /// 400: the request is wrong.
    pub fn input(error: Error) -> Failure {
        Failure { status: StatusCode::BAD_REQUEST, error }
    }

    /// 404: no run or entry has that id.
    pub fn unknown(error: Error) -> Failure {
        Failure { status: StatusCode::NOT_FOUND, error }
    }

    /// 409: the state does not allow the change.
    pub fn conflict(error: Error) -> Failure {
        Failure { status: StatusCode::CONFLICT, error }
    }

    /// 500: a file of the home could not be read or written.
    pub fn io(error: Error) -> Failure {
        Failure { status: StatusCode::INTERNAL_SERVER_ERROR, error }
    }
}

/// An engine or market-data error is the request's: its strategy, schedule
/// or market, checked at the input boundary.
impl From<Error> for Failure {
    fn from(error: Error) -> Failure {
        Failure::input(error)
    }
}

impl From<rusqlite::Error> for Failure {
    fn from(error: rusqlite::Error) -> Failure {
        Failure::io(Error::new(format!("the application database: {error}"), "data/app.sqlite"))
    }
}

impl IntoResponse for Failure {
    fn into_response(self) -> Response {
        (self.status, Json(serde_json::json!({ "error": self.error }))).into_response()
    }
}

/// A JSON request body; a body that is not the expected JSON gets 400 with
/// serde's message and the place `request`.
pub struct Body<T>(pub T);

impl<T: DeserializeOwned, S: Send + Sync> FromRequest<S> for Body<T> {
    type Rejection = Failure;

    async fn from_request(request: Request, state: &S) -> Result<Body<T>, Failure> {
        let bytes = Bytes::from_request(request, state).await.map_err(|e| Failure::input(Error::new(e.body_text(), "request")))?;
        serde_json::from_slice(&bytes).map(Body).map_err(|e| Failure::input(Error::new(e.to_string(), "request")))
    }
}

/// The `{id}` of a route's path; one that is not a number gets 400.
pub struct Id(pub i64);

impl<S: Send + Sync> FromRequestParts<S> for Id {
    type Rejection = Failure;

    async fn from_request_parts(parts: &mut Parts, state: &S) -> Result<Id, Failure> {
        let axum::extract::Path(text) = axum::extract::Path::<String>::from_request_parts(parts, state)
            .await
            .map_err(|e| Failure::input(Error::new(e.body_text(), "id")))?;
        text.parse().map(Id).map_err(|_| Failure::input(Error::new(format!("{text:?} is not an id"), "id")))
    }
}

/// Runs `work` on a blocking thread. A panic in it becomes a 500 reply.
pub async fn blocking<T: Send + 'static>(work: impl FnOnce() -> Result<T, Failure> + Send + 'static) -> Result<T, Failure> {
    tokio::task::spawn_blocking(work)
        .await
        .unwrap_or_else(|_| Err(Failure::io(Error::new("the request stopped on an internal error", "server"))))
}

/// The whole router: the API routes of each module, then the static files.
fn router(app: App) -> Router {
    let web = ServeDir::new(app.home.root().join("web"));
    Router::new()
        .merge(crate::runs::routes())
        .merge(crate::library::routes())
        // Each route module adds its routes here, with one line:
        // `.merge(crate::MODULE::routes())`, where `routes() -> Router<App>`.
        .merge(crate::formula::routes())
        .route("/api/{*rest}", any(|| async { Failure::unknown(Error::new("there is no such route", "path")) }))
        .method_not_allowed_fallback(|| async { Failure { status: StatusCode::METHOD_NOT_ALLOWED, error: Error::new("this route has no such method", "method") } })
        .fallback_service(web)
        .layer(middleware::from_fn(same_origin))
        .with_state(app)
}

/// The origin rule of the module comment.
async fn same_origin(request: Request, next: Next) -> Response {
    let headers = request.headers();
    if request.method() != Method::GET && request.method() != Method::HEAD {
        if let Some(origin) = headers.get(header::ORIGIN) {
            let host = headers.get(header::HOST).and_then(|h| h.to_str().ok()).unwrap_or_default();
            if origin.to_str().ok() != Some(&format!("http://{host}")) {
                let error = Error::new("a change must come from this website's own page", "Origin");
                return Failure { status: StatusCode::FORBIDDEN, error }.into_response();
            }
        }
    }
    next.run(request).await
}

/// `bt serve`: takes `data/serve.lock`, opens the database, holds a run
/// still marked running (the last server died while running it), listens
/// on `127.0.0.1:port` (0: a free port the system chooses), starts the
/// worker and calls `ready` with the address. Serves until Ctrl+C or
/// SIGTERM, then stops accepting requests, lets the open ones finish, stops
/// the worker, puts the run it interrupted back to waiting and returns.
pub fn serve(root: &Path, port: u16, ready: impl FnOnce(SocketAddr)) -> Result<(), Error> {
    let _lock = lock(root)?;
    let store = Store::open(root)?;
    store.interrupted("held").map_err(|failure| failure.error)?;
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let listener = std::net::TcpListener::bind(address).map_err(|e| Error::new(format!("cannot listen on {address}: {e}"), "port"))?;
    let address = listener.local_addr().map_err(|e| Error::new(e.to_string(), "port"))?;
    listener.set_nonblocking(true).map_err(|e| Error::new(e.to_string(), "port"))?;
    let runtime = tokio::runtime::Runtime::new().map_err(|e| Error::new(format!("cannot start the server: {e}"), "server"))?;
    let home = Home::new(root);
    let (worker, thread) = Worker::start(home.clone(), store.clone());
    let app = App { home, store: store.clone(), worker: worker.clone() };
    let served = runtime.block_on(async {
        let shutdown = signal()?;
        let listener = tokio::net::TcpListener::from_std(listener).map_err(|e| Error::new(e.to_string(), "port"))?;
        ready(address);
        axum::serve(listener, router(app))
            .with_graceful_shutdown(shutdown)
            .await
            .map_err(|e| Error::new(format!("the server stopped: {e}"), "server"))
    });
    worker.shutdown();
    thread.join().expect("the worker ends");
    served.and(store.interrupted("waiting").map_err(|failure| failure.error))
}

/// `data/serve.lock`, held while the server runs: one server per home.
fn lock(root: &Path) -> Result<File, Error> {
    let data = root.join("data");
    let path = data.join("serve.lock");
    std::fs::create_dir_all(&data).map_err(|e| Error::new(format!("cannot create the folder: {e}"), data.display()))?;
    let file = File::options()
        .create(true)
        .truncate(false)
        .write(true)
        .open(&path)
        .map_err(|e| Error::new(format!("cannot open the lock: {e}"), path.display()))?;
    match file.try_lock() {
        Ok(()) => Ok(file),
        Err(std::fs::TryLockError::WouldBlock) => Err(Error::new("another server is running on this home", path.display())),
        Err(std::fs::TryLockError::Error(e)) => Err(Error::new(format!("cannot take the lock: {e}"), path.display())),
    }
}

/// A future that ends at Ctrl+C (SIGINT) or SIGTERM. Both are caught from
/// this call on, before the server says it is ready.
fn signal() -> Result<impl Future<Output = ()>, Error> {
    use tokio::signal::unix::{SignalKind, signal};
    let catch = |kind| signal(kind).map_err(|e| Error::new(format!("cannot catch signals: {e}"), "server"));
    let (mut interrupt, mut terminate) = (catch(SignalKind::interrupt())?, catch(SignalKind::terminate())?);
    Ok(async move {
        tokio::select! {
            _ = interrupt.recv() => {}
            _ = terminate.recv() => {}
        }
    })
}
