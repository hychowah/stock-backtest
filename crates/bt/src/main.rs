use clap::Parser;

/// Stock screener and backtest.
#[derive(Parser)]
#[command(version)]
struct Cli {}

fn main() {
    Cli::parse();
}
