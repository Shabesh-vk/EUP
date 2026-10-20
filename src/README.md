# EUP Engine

The video engine behind EUP. Rust, no GC, no hidden control flow.

EUP is a renamed fork of [Concat](https://github.com/jub0t/Concat) by Jareer
and the Concat contributors, and stays under its licence, AGPL-3.0-or-later
(see `LICENSE` at the repository root). Only the name changed: projects saved by Concat
(`concat.json`) open as they are, and the first start moves Concat's settings
folder (`app.concat.editor`) to `app.eup.editor`. Built-in effect and text
preset ids keep their `concat.` namespace, since projects store them.

## Layout

| Crate | What it is | Dependencies |
|---|---|---|
| `eup-core` | Time, arena, frames, timeline model. The vocabulary every other crate speaks. | **none** (std only) |
| `eup-media` | Getting pixels and samples in and out of files. Links FFmpeg (libav*), and is the only crate that knows it exists. | `eup-core`, ffmpeg-the-third |
| `eup-project` | The edit itself: document model, operations as commands, undo, eup.json IO. | serde, serde_json |
| `eup-render` | Turning a timeline plus a timestamp into one finished frame. | `eup-core`, wgpu (optional) |
| `eup-effects` | Effect packages: manifests, WGSL shaders for pictures and FFmpeg chain templates for sound, the catalogue. Each built-in effect is a folder under `packages/`. | `eup-project`, serde, toml |
| `eup-export` | Timeline to file: flatten, the frame-by-frame render loop, the paused monitor's true frame. | `eup-core`, `eup-media`, `eup-render`, `eup-project`, `eup-effects` |
| `eup-api` | The EUP API: JSON requests in, responses and events out. Projects, edits, media, the catalogue, templates, exports as jobs, frames. | `eup-host`, `eup-export`, `eup-effects`, `eup-project` |
| `eup-server` | The API on a socket: JSON-RPC lines over TCP or a Unix socket, and gRPC behind the `grpc` feature. One dispatcher, many callers. | `eup-api`; tonic and tokio with `grpc` |
| `eup-cli` | A binary to drive the above: `probe`, `render`, `api` (the API over stdin and stdout) and `serve` (the API on a socket). | `eup-server`, `eup-api`, the engine crates |
| `eup-host` | What the window needs that is not the edit: sessions, project folders, previews, playback, templates, job slots. | `eup-media`, `eup-project`, `eup-export`, cpal |
| `eup-speech` | Transcription (whisper.cpp, in-process) and text to speech (Kokoro via sherpa-onnx). | `eup-host`, `eup-media`, whisper-rs, sherpa-onnx |
| `eup` | The editor window: every pane, dialog and primitive, in Slint. The app a user launches. | slint, `eup-host`, `eup-speech` |
| `eup-android` | The Android activity: the entry point that hosts the window on a phone. | `eup`, slint |

The dependency arrows point one way:

```
eup -> eup-speech -> eup-host -> {export, project, media} -> core
                                       -> render -> core
                                          export -> effects -> project
eup-cli -> eup-server -> eup-api -> eup-host
```

If you ever find yourself wanting `core` to depend on `media`, something has
been put in the wrong crate.

`eup` is the app. It opens project folders through `eup-host`, reads
the engine's project to draw the bin and the lanes, and writes every edit as
a `eup-project` command.

## Build and run

```sh
cargo build
cargo test
cargo run -p eup-cli -- probe some-video.mp4
cargo run -p eup-cli -- render some-video.mp4 out.mp4 --frames 120
cargo run -p eup-cli -- api '{"method":"catalogue.list","kind":"filter"}'
cargo run -p eup-cli -- api < edits.jsonl   # one JSON-RPC call per line; see below
cargo run -p eup-cli -- serve               # the same API on 127.0.0.1:7420
cargo run -p eup-cli --features grpc -- serve --grpc 127.0.0.1:7421
cargo run -p eup                    # the editor window, debug
cargo run --profile quick -p eup    # optimised, rebuilds in seconds: for trying changes
cargo build --profile app -p eup    # the shipping binary: fat LTO, panic=abort, stripped
```

Nothing is spawned at run time: FFmpeg is linked, whisper.cpp and sherpa-onnx
are compiled in. A build needs the FFmpeg 7+ development libraries (headers
and import libraries) - `brew install ffmpeg` on macOS, a BtbN `shared` build
unpacked and pointed at with `FFMPEG_DIR` on Windows and on Linux
distributions whose packaged FFmpeg is older than 7 - plus cmake and a C++
toolchain for whisper.cpp. The window draws with Slint's Skia renderer on
every platform, from prebuilt Skia binaries fetched at build time.
On Linux, Skia needs the fontconfig and freetype headers at build time (see
`.github/workflows/build-app.yml` for the package list).

On Nix, the flake at the repository root builds the window with every native
dependency pinned: `nix build` (then `./result/bin/eup`), `nix run`, or
`nix develop` for a shell with the toolchain and libraries in it. Linux
x86_64 and aarch64.

### Phones

The whole engine and the window build for Android (arm64) and iOS
(arm64). Two native libraries come from source for a phone, because no
prebuilt covers them: FFmpeg, which `scripts/ffmpeg-mobile.sh` cross-builds
as static archives with the platform's hardware codecs turned on -
MediaCodec on Android, VideoToolbox on iOS - and whisper.cpp, which its
crate builds with cmake for the target. sherpa-onnx ships as the shared
library k2-fsa publishes, fetched by `scripts/sherpa-mobile.sh`; on Android
the app carries it in `jniLibs`, on iOS as an embedded framework. Both
scripts leave their output under `vendor/`, outside `target/`, and
`scripts/mobile-env.sh` turns that into the build environment:

```sh
# Android: the NDK under the SDK, a JDK, and cargo-ndk or cargo-apk.
scripts/ffmpeg-mobile.sh aarch64-linux-android
scripts/sherpa-mobile.sh aarch64-linux-android
eval "$(scripts/mobile-env.sh aarch64-linux-android)"
cargo ndk -t arm64-v8a --platform 26 build -p eup-android   # the activity's .so
cargo apk build --release -p eup-android                     # the APK, signed with
                                                                # CARGO_APK_RELEASE_KEYSTORE

# iOS: Xcode.
scripts/ffmpeg-mobile.sh aarch64-apple-ios
scripts/sherpa-mobile.sh aarch64-apple-ios
eval "$(scripts/mobile-env.sh aarch64-apple-ios)"
cargo build --release -p eup --target aarch64-apple-ios
scripts/ios-app.sh aarch64-apple-ios release                    # EUP.app
```

`.github/workflows/mobile.yml` runs exactly this on every pull request
and on a release tag, and keeps the FFmpeg builds cached. The window is one library: `eup` on the
desktop and on iOS runs it from `main.rs`, `eup-android` from the
activity's `android_main`, and `crates/eup/src/platform.rs` is where
the three differ - how the backend is chosen, how files are picked, and
whether there is a title strip to drag.

## Driving EUP without the window

The full reference - every method, every edit command, every type, and a
page per transport - lives on the website at
[concatenate.pages.dev/docs](https://concatenate.pages.dev/docs). What follows
is the short version.

Everything the window does to a project, a script can do through the EUP
API: `eup-api` is the one dispatcher, and the transports only carry it.
On a line - stdin, TCP, a Unix socket - a call is JSON-RPC 2.0, one object
per line, and the response comes back with the call's id:

```jsonl
{"jsonrpc":"2.0","id":1,"method":"project.open","params":{"path":"/edits/Reel"}}
{"jsonrpc":"2.0","id":1,"result":{"project":{...},"canUndo":false,...}}
{"jsonrpc":"2.0","id":2,"method":"edit.apply","params":{"path":"/edits/Reel","command":{"op":"addTextClip","start":1.5}}}
{"jsonrpc":"2.0","id":2,"result":{...}}
{"jsonrpc":"2.0","id":3,"method":"export.run","params":{"path":"/edits/Reel","output":"/edits/reel.mp4"}}
{"jsonrpc":"2.0","id":3,"result":{"job":"j1","path":"/edits/Reel","output":"/edits/reel.mp4"}}
{"jsonrpc":"2.0","method":"export.progress","params":{"job":"j1","path":"/edits/Reel","frame":30,"total":900,"stage":"video"}}
{"jsonrpc":"2.0","method":"export.done","params":{"job":"j1","path":"/edits/Reel","output":"/edits/reel.mp4","width":1920,"height":1080}}
```

An `edit.apply` carries a `eup-project` command as it is, so every edit
the window can make is one a caller can make, with the same refusals. An
error is `{"code": -32001, "message": "...", "data": {"code": "notOpen"}}`:
the number is JSON-RPC's, the name in `data` is the API's - `parse`,
`invalid`, `notOpen`, `notFound`, `refused`, `busy`, `cancelled`, `failed`,
`unauthorized`. Exports are jobs: the response names one at once and its
events follow, to every connected caller, each naming its job and project.

`eup-cli serve` puts the same lines on a socket. It binds loopback unless
told otherwise, and every connection, loopback included, presents a token
as its first line, `{"jsonrpc":"2.0","id":0,"method":"auth","params":{"token":"..."}}`:
the one given with `--token` (or `EUP_API_TOKEN`), or else one minted
at start and printed under the addresses, so only whoever started the
server can hand it out. There is no encryption; a bind off loopback belongs
behind something that has it. With the `grpc` feature the same API is
served over HTTP/2 from `crates/eup-server/proto/eup.proto`, a thin
envelope carrying the same JSON, with the token as `authorization: Bearer
...` metadata. `version` is the call to make first: its reply's
`capabilities` names what the build serves (`events`, `json-rpc`,
`unix-socket`, `grpc`, `gpu`) before anything is asked of it.

## Reading this codebase cold

1. The layout table and dependency arrows above - the map of the whole system.
2. `crates/*/src/lib.rs` - every crate opens with a `//!` block saying what it is for.
3. `cargo doc --open` - the generated API map of the whole engine.

## Conventions

- **Time is exact.** All timestamps are `eup_core::time::Rational` seconds, never `f64`.
  Frame-accurate editing and floating point do not mix.
- **Graphs use handles, not pointers.** `eup_core::arena` explains why.
- **Shallow generics.** Concrete types until three call sites demand otherwise.
- **Threads, not async.** The render path is CPU-bound; `async` buys nothing here.
