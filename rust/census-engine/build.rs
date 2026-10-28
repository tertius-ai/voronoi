// SPDX-License-Identifier: MIT
fn main() {
    // Dependency build scripts do not propagate loader paths to this binary.
    // Use the same pkg-config installation as flint-sys, not a system fallback.
    let flint = pkg_config::Config::new()
        .atleast_version("3.6")
        .probe("flint")
        .expect("FLINT 3.6+ is required; see the Noether 0.3.2 setup in README.md");
    for directory in flint.link_paths {
        println!("cargo:rustc-link-arg=-Wl,-rpath,{}", directory.display());
    }
    // Production snapshots retain native dependencies next to the copied worker.
    let origin = if cfg!(target_os = "macos") {
        "@loader_path"
    } else {
        "$ORIGIN"
    };
    println!("cargo:rustc-link-arg=-Wl,-rpath,{origin}/../python/tertius_noether.libs");
}
