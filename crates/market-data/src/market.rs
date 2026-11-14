use crate::Error;
use serde::{Deserialize, Serialize};
use std::str::FromStr;

/// A stock market whose data the program prepares and reads.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Market {
    Us,
    Hk,
    Jp,
}

impl Market {
    /// Every market, in the order commands report them.
    pub const ALL: [Market; 3] = [Market::Us, Market::Hk, Market::Jp];

    /// The market's id: `us`, `hk` or `jp`. Folder names and replies use it.
    pub fn id(self) -> &'static str {
        match self {
            Market::Us => "us",
            Market::Hk => "hk",
            Market::Jp => "jp",
        }
    }
}

/// Reads a market id; the error names the input `market`.
impl FromStr for Market {
    type Err = Error;

    fn from_str(text: &str) -> Result<Market, Error> {
        Market::ALL
            .into_iter()
            .find(|m| m.id() == text)
            .ok_or_else(|| Error::new(format!("unknown market {text:?}: use us, hk or jp"), "market"))
    }
}
