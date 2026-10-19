//! Writes the JSON Schemas of the timeline and the per-step outcome:
//! `cargo run -p incubrix-core --example schema`.

fn main() {
    let out = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../schema");
    std::fs::create_dir_all(&out).unwrap();
    let write = |name: &str, schema: schemars::schema::RootSchema| {
        let path = out.join(name);
        std::fs::write(&path, serde_json::to_string_pretty(&schema).unwrap() + "\n").unwrap();
        println!("wrote {}", path.display());
    };
    write(
        "timeline.schema.json",
        schemars::schema_for!(incubrix_core::Timeline),
    );
    write(
        "project.schema.json",
        schemars::schema_for!(incubrix_core::Project),
    );
    write(
        "outcome.schema.json",
        schemars::schema_for!(incubrix_core::Outcome),
    );
    write("op.schema.json", schemars::schema_for!(incubrix_core::Op));
}
