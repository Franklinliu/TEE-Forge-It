1. Outdated migration -> err: human migration inconsistencies

In the following case `regex-sgx`, the migration code is outdated and does not align with the latest migration strategy.

```bash
automerge/sgx-world/extracted_changes/regex-sgx_changes.txt
Changes in src/lib.rs:
diff --git a/src/lib.rs b/src/lib.rs
index 2a74bf81..d749b3a5 100644
--- a/src/lib.rs
+++ b/src/lib.rs
@@ -616,8 +616,17 @@ another matching engine with fixed memory requirements.
 #![cfg_attr(test, deny(warnings))]
 #![cfg_attr(feature = "pattern", feature(pattern))]
 
-#[cfg(not(feature = "std"))]
-compile_error!("`std` feature is currently required to build this crate");
+#![cfg_attr(not(target_env = "sgx"), no_std)]
+#![cfg_attr(target_env = "sgx", feature(rustc_private))]
+
+#[cfg(feature = "perf-literal")]
+
+#[cfg(target_env = "sgx")]
+extern crate core;
+
+#[cfg(not(target_env = "sgx"))]
+#[macro_use]
+extern crate sgx_tstd as std;
 
 #[cfg(feature = "perf-literal")]
 extern crate aho_corasick;
```

2. Solve compilation issues

use sgx-world/byte-slice-cast-sgx/sgx/byte-slice-cast-sgx-test as an example.

error message :
```bash
GEN  =>  enclave/Enclave_t.c enclave/Enclave_t.h app/Enclave_u.c app/Enclave_u.h
CC   <=  enclave/Enclave_t.c
ar rcsD app/libEnclave_u.a app/Enclave_u.o
cp app/libEnclave_u.a ./lib
    Updating crates.io index
    Updating git repository `https://github.com/apache/teaclave-sgx-sdk.git`
error: failed to download `libc v0.2.175`

Caused by:
  unable to get packages from source

Caused by:
  failed to parse manifest at `/root/.cargo/registry/src/github.com-1ecc6299db9ec823/libc-0.2.175/Cargo.toml`

Caused by:
  failed to parse the `edition` key

Caused by:
  this version of Cargo is older than the `2021` edition, and only supports `2015` and `2018` editions.
```

Root cause is libc version control. One fix is:
```bash 
app/Cargo.toml
[package]
name = "app"
version = "1.0.0"
authors = ["Baidu"]
build = "build.rs"

[dependencies]
sgx_types = { rev = "v1.1.3", git = "https://github.com/apache/teaclave-sgx-sdk.git" }
sgx_urts = { rev = "v1.1.3", git = "https://github.com/apache/teaclave-sgx-sdk.git" }
dirs = "1.0.2"
+libc = "=0.2.77"
```

error message:
```bash
 Compiling compiler_builtins v0.1.35
   Compiling core v0.0.0 (/root/.rustup/toolchains/nightly-2020-10-25-x86_64-unknown-linux-gnu/lib/rustlib/src/rust/library/core)
   Compiling rustc-std-workspace-core v1.99.0 (/root/.rustup/toolchains/nightly-2020-10-25-x86_64-unknown-linux-gnu/lib/rustlib/src/rust/library/rustc-std-workspace-core)
   Compiling alloc v0.0.0 (/root/.rustup/toolchains/nightly-2020-10-25-x86_64-unknown-linux-gnu/lib/rustlib/src/rust/library/alloc)
    Finished release [optimized] target(s) in 16.81s
    Updating git repository `https://github.com/apache/teaclave-sgx-sdk.git`
warning: fetching `master` branch from `https://github.com/apache/teaclave-sgx-sdk.git` but the `HEAD` reference for this repository is not the `master` branch. This behavior will change in Cargo in the future and your build may break, so it's recommended to place `branch = "master"` in Cargo.toml when depending on this git repository to ensure that your build will continue to work.
error: no matching package named `panic_abort` found
location searched: https://github.com/apache/teaclave-sgx-sdk.git
required by package `sysroot v0.0.0 (/tmp/xargo.YEXAwFmB3LsX)`
```

Root cause is git repository evolution. One fix is to specify version of git repo. 
```bash 
Cargo.toml
[dependencies]
alloc = {}

[dependencies.sgx_types]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
+rev = "= "v1.1.3""
stage = 1

[dependencies.sgx_alloc]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 1

[dependencies.sgx_unwind]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 1

[dependencies.sgx_demangle]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 1

[dependencies.panic_abort]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 1

[dependencies.sgx_libc]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 2

[dependencies.sgx_tkey_exchange]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 2

[dependencies.sgx_tse]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 2

[dependencies.sgx_tcrypto]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 2

[dependencies.sgx_trts]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 3

[dependencies.sgx_backtrace_sys]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 3

[dependencies.panic_unwind]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 3

[dependencies.sgx_tdh]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 4

[dependencies.sgx_tseal]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 4

[dependencies.sgx_tprotected_fs]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 4

[dependencies.std]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
features = ["untrusted_fs", "backtrace", "net"]
stage = 5

[dependencies.sgx_no_tstd]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 5

[dependencies.sgx_rand]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 6

[dependencies.sgx_serialize]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 6

[dependencies.sgx_tunittest]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 6

[dependencies.sgx_backtrace]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 7

[dependencies.sgx_cov]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 7

[dependencies.sgx_signal]
git = "https://github.com/apache/teaclave-sgx-sdk.git"
stage = 7
```

error message:
```bash
   Compiling sgx_signal v1.1.3 (https://github.com/apache/teaclave-sgx-sdk.git?rev=v1.1.3#a6a172e6)
    Finished release [optimized] target(s) in 0.87s
    Updating git repository `https://github.com/apache/teaclave-sgx-sdk.git`
    Updating crates.io index
error: failed to download `cc v1.1.1`

Caused by:
  unable to get packages from source

Caused by:
  failed to parse manifest at `/root/.cargo/registry/src/github.com-1ecc6299db9ec823/cc-1.1.1/Cargo.toml`

Caused by:
  Feature `parallel` includes `dep:libc` which is neither a dependency nor another feature
Makefile:39: recipe for target 'libenclave.a' failed
make[1]: *** [libenclave.a] Error 101
make[1]: Leaving directory '/root/sgx-world/byte-slice-cast-sgx/sgx/byte-slice-cast-sgx-test/enclave'
```

Root cause is cc version. One fix is:
```bash 
cargo update -p cc --precise 1.0.92
```

Note cc-v1.0.92 does not work for sgx-world/anyhow-sgx.
Use 1.0.28 instead.
```bash 
cargo update -p cc --precise 1.0.28
```