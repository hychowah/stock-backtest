use std::process::Command;

#[test]
fn version_flag_prints_the_package_version() {
    let output = Command::new(env!("CARGO_BIN_EXE_bt"))
        .arg("--version")
        .output()
        .expect("run bt");
    assert!(output.status.success());
    let text = String::from_utf8(output.stdout).unwrap();
    assert_eq!(text.trim(), format!("bt {}", env!("CARGO_PKG_VERSION")));
}
