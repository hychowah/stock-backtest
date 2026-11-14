use serde::Serialize;
use std::fmt;

/// Why a command failed. `bt` prints it as `{"error": {"message", "place"}}`
/// and exits with status 1. Commands check their inputs once, at the start;
/// an error names the input, file or folder at fault in `place`.
#[derive(Debug, Clone, Serialize)]
pub struct Error {
    /// What went wrong and, where the user can act, what to do.
    pub message: String,
    /// The input (such as `market`), file or folder the message is about.
    pub place: String,
}

impl Error {
    pub fn new(message: impl Into<String>, place: impl fmt::Display) -> Error {
        Error { message: message.into(), place: place.to_string() }
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.place, self.message)
    }
}
