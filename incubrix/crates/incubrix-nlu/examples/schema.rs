//! Writes the JSON Schema of an intent - the only thing a parser, including
//! an LLM, may produce: `cargo run -p incubrix-nlu --example schema`.

fn main() {
    let path =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../schema/intent.schema.json");
    let schema = schemars::schema_for!(incubrix_nlu::Intent);
    std::fs::write(&path, serde_json::to_string_pretty(&schema).unwrap() + "\n").unwrap();
    println!("wrote {}", path.display());
}
