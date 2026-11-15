//! Downloads from the data provider into `raw/`: the client
//! ([`provider`]), the rules of what an update asks for (`plan`) and the
//! update itself ([`update`]).

mod plan;
pub mod provider;
pub mod update;
