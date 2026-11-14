//! The command-line guide (`docs/command-line.md`): every strategy file that it
//! shows in a `json` block passes `bt check`.

mod common;

use std::path::Path;

/// The text of every fenced block whose info string is `json`.
fn json_blocks(page: &str) -> Vec<String> {
    let mut blocks = Vec::new();
    let mut current: Option<String> = None;
    let mut other_fence = false;
    for line in page.lines() {
        match (&mut current, line.trim_end()) {
            (Some(_), "```") => blocks.extend(current.take()),
            (Some(block), text) => {
                block.push_str(text);
                block.push('\n');
            }
            (None, "```json") if !other_fence => current = Some(String::new()),
            (None, text) if text.starts_with("```") => other_fence = !other_fence,
            _ => {}
        }
    }
    assert!(current.is_none() && !other_fence, "a fenced block is not closed");
    blocks
}

#[test]
fn every_strategy_file_in_the_guide_passes_check() {
    let page = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../docs/command-line.md");
    let blocks = json_blocks(&std::fs::read_to_string(page).expect("read the guide"));
    assert!(blocks.len() >= 3, "the guide shows {} strategy files; it is expected to show at least 3", blocks.len());
    let dir = tempfile::tempdir().unwrap();
    for (n, block) in blocks.iter().enumerate() {
        let file = dir.path().join(format!("example-{}.json", n + 1));
        std::fs::write(&file, block).unwrap();
        let (reply, success) = common::bt(&["check", common::path(&file)]);
        assert!(success, "json block {} of the guide is refused: {reply}\n{block}", n + 1);
    }
}
