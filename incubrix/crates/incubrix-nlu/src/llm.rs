//! A language model as a parser: Claude, OpenAI or a local Ollama model.
//!
//! The model reads the instruction in plain English, with a little context
//! (length, captions, speakers, the question waiting for an answer) and the
//! JSON Schema of [`Intent`], and answers with one intent. Its answer is
//! checked against the schema; a malformed one gets a single correction
//! round. Every good answer is cached by the hash of (provider, model,
//! prompt, context), so a rerun of a session reads the cache and gets the
//! same intents without a network call. Anything unusable becomes
//! `Intent::Unknown` - the model never reaches the timeline.
//!
//! Claude is called over raw HTTP (there is no official Rust SDK). The
//! current Claude models reject sampling parameters, so determinism comes
//! from the cache rather than from `temperature`.

use std::path::PathBuf;
use std::time::Duration;

use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use crate::intent::Intent;
use crate::{Context, Parser};

/// Which service.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Provider {
    /// Anthropic Messages API.
    Anthropic,
    /// OpenAI Chat Completions.
    OpenAi,
    /// A local Ollama server.
    Ollama,
}

impl Provider {
    fn name(self) -> &'static str {
        match self {
            Provider::Anthropic => "anthropic",
            Provider::OpenAi => "openai",
            Provider::Ollama => "ollama",
        }
    }

    /// How the provider is shown to people.
    pub fn label(self) -> &'static str {
        match self {
            Provider::Anthropic => "Claude",
            Provider::OpenAi => "OpenAI",
            Provider::Ollama => "Ollama (local)",
        }
    }
}

/// The default Claude model.
pub const CLAUDE_MODEL: &str = "claude-opus-5-5";

/// Settings, normally from the environment.
#[derive(Clone, Debug)]
pub struct LlmConfig {
    /// The service.
    pub provider: Provider,
    /// Model name.
    pub model: String,
    /// API key (not needed for Ollama).
    pub api_key: Option<String>,
    /// Base URL (Ollama, a proxy, or a test server).
    pub base_url: String,
    /// Where answers are cached.
    pub cache_dir: PathBuf,
}

fn var(k: &str) -> Option<String> {
    std::env::var(k).ok().filter(|v| !v.trim().is_empty())
}

impl LlmConfig {
    /// From `NLU_PROVIDER`, `NLU_MODEL`, `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`,
    /// `NLU_BASE_URL` / `OLLAMA_URL` and `NLU_CACHE_DIR`. Defaults to Claude.
    pub fn from_env() -> Self {
        let provider = match var("NLU_PROVIDER")
            .unwrap_or_default()
            .to_lowercase()
            .as_str()
        {
            "openai" => Provider::OpenAi,
            "ollama" => Provider::Ollama,
            _ => Provider::Anthropic,
        };
        Self::for_provider(provider)
    }

    /// The model the environment sets up, if any: an explicit `NLU_PROVIDER`
    /// (`anthropic`, `openai`, `ollama`), else whichever API key is present.
    /// `None` when nothing is configured - the rules then work alone.
    pub fn detect() -> Option<Self> {
        let provider = match var("NLU_PROVIDER")
            .unwrap_or_default()
            .to_lowercase()
            .as_str()
        {
            "anthropic" | "claude" | "llm" => Provider::Anthropic,
            "openai" => Provider::OpenAi,
            "ollama" => Provider::Ollama,
            "rules" | "mock" => return None,
            _ if var("ANTHROPIC_API_KEY").is_some() => Provider::Anthropic,
            _ if var("OPENAI_API_KEY").is_some() => Provider::OpenAi,
            // No key: a local Ollama with a model pulled will do.
            _ => {
                let mut cfg = Self::for_provider(Provider::Ollama);
                let model = ollama_model(&cfg.base_url)?;
                if var("NLU_MODEL").is_none() {
                    cfg.model = model;
                }
                return Some(cfg);
            }
        };
        let mut cfg = Self::for_provider(provider);
        if provider == Provider::Ollama && var("NLU_MODEL").is_none() {
            if let Some(m) = ollama_model(&cfg.base_url) {
                cfg.model = m;
            }
        }
        Some(cfg)
    }

    /// [`LlmConfig::detect`], remembered: it may probe a local Ollama
    /// server, which a window redrawing must not wait on every time.
    ///
    /// A model found is kept; while none is found, the check is repeated at
    /// most every 10 s, so a local server started later is picked up.
    pub fn detected() -> Option<Self> {
        use std::sync::Mutex;
        use std::time::Instant;
        static LAST: Mutex<Option<(Option<LlmConfig>, Instant)>> = Mutex::new(None);
        let mut last = LAST.lock().unwrap_or_else(|e| e.into_inner());
        if let Some((cfg, at)) = &*last {
            if cfg.is_some() || at.elapsed() < Duration::from_secs(10) {
                return cfg.clone();
            }
        }
        let cfg = Self::detect();
        *last = Some((cfg.clone(), Instant::now()));
        cfg
    }

    fn for_provider(provider: Provider) -> Self {
        let (model, key, url) = match provider {
            Provider::Anthropic => (
                CLAUDE_MODEL,
                var("ANTHROPIC_API_KEY"),
                "https://api.anthropic.com".to_owned(),
            ),
            Provider::OpenAi => (
                "gpt-4o-mini",
                var("OPENAI_API_KEY"),
                "https://api.openai.com".to_owned(),
            ),
            Provider::Ollama => (
                "llama3.1",
                None,
                var("OLLAMA_URL").unwrap_or_else(|| "http://127.0.0.1:11434".into()),
            ),
        };
        Self {
            provider,
            model: var("NLU_MODEL").unwrap_or_else(|| model.into()),
            api_key: key,
            base_url: var("NLU_BASE_URL").unwrap_or(url),
            cache_dir: var("NLU_CACHE_DIR")
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from(".incubrix-cache/nlu")),
        }
    }
}

/// Models to prefer from a local Ollama, best first.
const OLLAMA_PREFERRED: &[&str] = &["llama3.1", "qwen2.5", "llama3", "mistral"];

/// A model installed in the Ollama server at `base`, if one answers fast.
fn ollama_model(base: &str) -> Option<String> {
    let v: Value = ureq::get(&format!("{}/api/tags", base.trim_end_matches('/')))
        .timeout(Duration::from_millis(1500))
        .call()
        .ok()?
        .into_string()
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())?;
    let names: Vec<String> = v["models"]
        .as_array()?
        .iter()
        .filter_map(|m| m["name"].as_str().map(str::to_owned))
        .collect();
    OLLAMA_PREFERRED
        .iter()
        .find_map(|p| names.iter().find(|n| n.starts_with(p)).cloned())
        .or_else(|| names.first().cloned())
}

/// The LLM parser.
#[derive(Clone, Debug)]
pub struct LlmParser {
    cfg: LlmConfig,
}

/// The instructions every model gets.
pub const SYSTEM_PROMPT: &str = r##"You turn ONE video-editing request, written in plain English by a creator, into ONE JSON object. Output only that JSON object: no prose, no code fences.

You never edit the video and never work out positions. Times are milliseconds of the video AS IT PLAYS NOW. The message lists every time the user said under "times_in_ms", already converted exactly ("half a minute" = 30000, "1:20" = 80000): use those numbers as they are, never your own arithmetic.

The JSON object is exactly one of these shapes ("intent" is always present):
{"intent":"cut","target":T}                       remove part of the video
{"intent":"keep_only","target":T}                 remove everything else
{"intent":"move","target":T,"to":P}
{"intent":"speed","target":T,"speed":N}           N in thousandths: 2000 = twice as fast, 500 = half speed
{"intent":"mute","target":T}   {"intent":"bleep","target":T}
{"intent":"add_caption","text":"words shown","target":T}   ONE caption whose words the user gave (usually in quotes) - never invent the text
{"intent":"style_caption","caption":C,"change":{...}}   "change" holds ONLY what the user asked to change, any of: "color":"#RRGGBB", "size":{"kind":"bigger"} / {"kind":"smaller"} / {"kind":"px","px":60}, "position":"top"|"center"|"bottom", "bold":true|false
{"intent":"retext_caption","caption":C,"text":"new words"}
{"intent":"remove_caption","caption":C}
{"intent":"auto_caption"}                         captions for everything said ("add captions", "add subtitles", "caption the video") - the editor writes the words itself
{"intent":"remove_fillers"}   {"intent":"remove_silences","min_ms":N}
{"intent":"keep_pause","target":T}
{"intent":"add_music","path":"file name"}   {"intent":"remove_music"}
{"intent":"undo","steps":1}   {"intent":"redo","steps":1}
{"intent":"restore","edit":E}                     bring back something removed earlier; add "keep":"music" only if the user says "but keep the music"
{"intent":"render"}                               only when the user asks to export or render
{"intent":"vague","goal":"boring"}  or "shorter"  for requests too vague to act on ("the boring bit", "tighten it up") - never guess a span
{"intent":"multi","parts":[{"text":"first request","intent":{...}},{"text":"second request","intent":{...}}]}   several requests in one message
{"intent":"talk","topic":"greeting"}              conversation, not an edit. topic: greeting ("hi"), thanks, help ("what can you do?"), status ("how long is my video?"), history ("what have you changed?"), smalltalk (anything else friendly)
{"intent":"talk","topic":"smalltalk","reply":"..."}   for smalltalk only: one or two warm, personal sentences, like a friendly neighbour who happens to edit video (never "I'm just a program"). Never state facts about the video (lengths, changes) - the editor adds those itself.
{"intent":"unknown","reason":"why"}               an editing request you cannot make sense of

T, what it applies to:
{"kind":"range","start_ms":N,"end_ms":N}   {"kind":"first","ms":N}   {"kind":"last","ms":N}
{"kind":"from","start_ms":N}   {"kind":"until","end_ms":N}   {"kind":"at","ms":N}
{"kind":"phrase","text":"exact words said"}   {"kind":"topic","text":"subject"}
{"kind":"after_phrase","text":"words"}   {"kind":"before_phrase","text":"words"}
{"kind":"speaker","who":{"kind":"guest"},"topic":"subject"}   (who: host or guest; topic optional)
{"kind":"profanity"}   {"kind":"everything"}   {"kind":"that"} (the part the last request touched)
Phrase, topic and after/before targets may add "occurrence":{"kind":"nth","n":2}, {"kind":"last"} or {"kind":"all"} when the user says which mention.

C, which caption: {"kind":"that"} ("it", "that caption")  {"kind":"all"} ("the captions", "all captions", plural)  {"kind":"nth","value":2}  {"kind":"text","value":"words on it"}
P, where to: {"kind":"start"}  {"kind":"end"}  {"kind":"at","ms":N}  {"kind":"before_phrase","text":"words"}
E, which earlier edit: {"kind":"intro"}  {"kind":"removed"} (what was removed, unspecified)  {"kind":"id","id":3}
   {"kind":"recent","edit":"cut","back":0} (back 0 = the last one, 1 = second-to-last; edit: cut|speed|caption|audio|music|move|any)  {"kind":"topic","text":"subject"}

Examples:
"trim off the opening half minute" -> {"intent":"cut","target":{"kind":"first","ms":30000}}
"lose everything after I say thanks for watching" -> {"intent":"cut","target":{"kind":"after_phrase","text":"thanks for watching"}}
"get rid of the bit where I talk about money" -> {"intent":"cut","target":{"kind":"topic","text":"money"}}
"play 1:00 till 1:30 twice as fast" -> {"intent":"speed","target":{"kind":"range","start_ms":60000,"end_ms":90000},"speed":2000}
"put 'Welcome!' on screen when I say welcome to the channel" -> {"intent":"add_caption","text":"Welcome!","target":{"kind":"phrase","text":"welcome to the channel"}}
"add captions" -> {"intent":"auto_caption"}
"put subtitles on the video please" -> {"intent":"auto_caption"}
"make that caption a bit larger and red" -> {"intent":"style_caption","caption":{"kind":"that"},"change":{"color":"#FF0000","size":{"kind":"bigger"}}}
"the welcome caption should sit at the top" -> {"intent":"style_caption","caption":{"kind":"text","value":"welcome"},"change":{"position":"top"}}
"bring the intro back" -> {"intent":"restore","edit":{"kind":"intro"}}
"go back one step" -> {"intent":"undo","steps":1}
"clean up the ums and the long pauses" -> {"intent":"multi","parts":[{"text":"clean up the ums","intent":{"intent":"remove_fillers"}},{"text":"the long pauses","intent":{"intent":"remove_silences","min_ms":1000}}]}
"hi there!" -> {"intent":"talk","topic":"greeting"}
"hey, can you cut the first 10 seconds" -> {"intent":"cut","target":{"kind":"first","ms":10000}}
"what can you do?" -> {"intent":"talk","topic":"help"}
"how long is the video now?" -> {"intent":"talk","topic":"status"}
"thanks, that looks great" -> {"intent":"talk","topic":"thanks"}
"how are you today?" -> {"intent":"talk","topic":"smalltalk","reply":"I'm doing well, thanks for asking - it's a good day for editing!"}
"what's the weather like?" -> {"intent":"talk","topic":"smalltalk","reply":"I can't check the weather from here, but I hope it's a nice one where you are!"}"##;

/// Instructions for reading a reply to a question.
pub const CHOOSE_PROMPT: &str = r#"A video editor asked the user a question with numbered options. Decide which option the user's reply picks.
Output only JSON: {"option": N} with N the 1-based option number, {"option": 0} if the reply cancels ("never mind", "none of them"), or {"option": null} if the reply does not answer the question (for example it is a new, different instruction)."#;

impl LlmParser {
    /// A parser with these settings.
    pub fn new(cfg: LlmConfig) -> Self {
        Self { cfg }
    }

    /// A parser configured from the environment.
    pub fn from_env() -> Self {
        Self::new(LlmConfig::from_env())
    }

    /// The settings in use.
    pub fn config(&self) -> &LlmConfig {
        &self.cfg
    }

    /// "Claude (claude-opus-5-5)", for people.
    pub fn label(&self) -> String {
        format!("{} ({})", self.cfg.provider.label(), self.cfg.model)
    }

    fn system(&self) -> String {
        SYSTEM_PROMPT.to_owned()
    }

    fn user(text: &str, ctx: &Context) -> String {
        let times: Vec<Value> = crate::times::mentions(text)
            .into_iter()
            .map(|(said, ms)| json!({"said": said, "ms": ms}))
            .collect();
        json!({ "instruction": text, "times_in_ms": times, "context": ctx }).to_string()
    }

    fn key_of(&self, parts: &[&str]) -> String {
        let mut h = Sha256::new();
        h.update(self.cfg.provider.name().as_bytes());
        h.update([0]);
        h.update(self.cfg.model.as_bytes());
        for part in parts {
            h.update([0]);
            h.update(part.as_bytes());
        }
        h.finalize().iter().map(|b| format!("{b:02x}")).collect()
    }

    /// The cache key for one instruction.
    pub fn cache_key(&self, text: &str, ctx: &Context) -> String {
        self.key_of(&[&self.system(), &Self::user(text, ctx)])
    }

    fn cached(&self, key: &str) -> Option<String> {
        std::fs::read_to_string(self.cfg.cache_dir.join(format!("{key}.json"))).ok()
    }

    fn store(&self, key: &str, json: &str) {
        if std::fs::create_dir_all(&self.cfg.cache_dir).is_ok() {
            let _ = std::fs::write(self.cfg.cache_dir.join(format!("{key}.json")), json);
        }
    }

    /// One round trip. `turns` alternate user / assistant, starting with the
    /// user; for Claude an assistant turn is its full `content` array as it
    /// came back, echoed unchanged.
    fn call(
        &self,
        system: &str,
        turns: &[Value],
        schema: &Value,
    ) -> Result<(String, Value), String> {
        let base = self.cfg.base_url.trim_end_matches('/');
        let key = || {
            self.cfg.api_key.clone().ok_or_else(|| {
                format!(
                    "no API key for {} (set ANTHROPIC_API_KEY or OPENAI_API_KEY)",
                    self.cfg.provider.label()
                )
            })
        };
        let messages: Vec<Value> = turns
            .iter()
            .enumerate()
            .map(|(i, c)| json!({"role": if i % 2 == 0 { "user" } else { "assistant" }, "content": c}))
            .collect();
        let (url, body, req) = match self.cfg.provider {
            Provider::Anthropic => {
                let url = format!("{base}/v1/messages");
                let body = json!({
                    "model": self.cfg.model,
                    "max_tokens": 16000,
                    "system": system,
                    "messages": messages,
                    // A translation, not a hard problem: low effort keeps it quick.
                    "output_config": {"effort": "low"},
                    // A declined request is re-run on Anthropic's recommended model.
                    "fallbacks": "default",
                });
                let req = ureq::post(&url)
                    .set("x-api-key", &key()?)
                    .set("anthropic-version", "2023-06-01")
                    .set("anthropic-beta", "server-side-fallback-2026-07-01");
                (url, body, req)
            }
            Provider::OpenAi => {
                let url = format!("{base}/v1/chat/completions");
                let mut all = vec![json!({"role": "system", "content": system})];
                all.extend(messages);
                let body = json!({
                    "model": self.cfg.model, "temperature": 0, "seed": 0,
                    "response_format": {"type": "json_object"}, "messages": all,
                });
                let req = ureq::post(&url).set("authorization", &format!("Bearer {}", key()?));
                (url, body, req)
            }
            Provider::Ollama => {
                let url = format!("{base}/api/chat");
                let mut all = vec![json!({"role": "system", "content": system})];
                all.extend(messages);
                let body = json!({
                    // A small schema ("which option?") is enforced by constrained
                    // decoding; an intent is free JSON, checked afterwards: under
                    // a grammar a small model takes the shortest valid branch.
                    "model": self.cfg.model, "stream": false,
                    "format": if schema.is_null() { json!("json") } else { schema.clone() },
                    "options": {"temperature": 0, "seed": 0}, "messages": all,
                });
                (url.clone(), body, ureq::post(&url))
            }
        };
        let resp = req
            .set("content-type", "application/json")
            .timeout(Duration::from_secs(90))
            .send_string(&body.to_string())
            .map_err(|e| match e {
                ureq::Error::Status(code, r) => {
                    let detail = r.into_string().unwrap_or_default();
                    format!(
                        "{url} answered {code}: {}",
                        detail.chars().take(300).collect::<String>()
                    )
                }
                other => format!("{url}: {other}"),
            })?;
        let v: Value = serde_json::from_str(&resp.into_string().map_err(|e| e.to_string())?)
            .map_err(|e| format!("unreadable reply: {e}"))?;
        match self.cfg.provider {
            Provider::Anthropic => {
                if v["stop_reason"] == "refusal" {
                    return Err("the model declined this request".into());
                }
                // Thinking blocks may come first: take the text.
                let text = v["content"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter(|b| b["type"] == "text")
                    .filter_map(|b| b["text"].as_str())
                    .collect::<Vec<_>>()
                    .join("");
                Ok((text, v["content"].clone()))
            }
            Provider::OpenAi => {
                let t = v["choices"][0]["message"]["content"]
                    .as_str()
                    .unwrap_or_default()
                    .to_owned();
                Ok((t.clone(), json!(t)))
            }
            Provider::Ollama => {
                let t = v["message"]["content"]
                    .as_str()
                    .unwrap_or_default()
                    .to_owned();
                Ok((t.clone(), json!(t)))
            }
        }
    }

    /// Asks the model, checks the answer, and gives it one chance to fix a
    /// malformed one. Returns the checked JSON text.
    fn ask<T: serde::de::DeserializeOwned>(
        &self,
        schema: &Value,
        system: &str,
        user: &str,
    ) -> Result<(T, String), String> {
        let first = json!(user);
        let (text, content) = self.call(system, std::slice::from_ref(&first), schema)?;
        match extract::<T>(&text) {
            Ok(found) => Ok(found),
            Err(why) => {
                let fix = json!(format!(
                    "That was not valid: {why}. Reply with only the corrected JSON object."
                ));
                let (text, _) = self.call(system, &[first, content, fix], schema)?;
                extract::<T>(&text)
            }
        }
    }

    /// Which option of a question a free-form reply picks: `Some(Some(i))`
    /// an option, `Some(None)` a cancel, `None` not an answer (or no model).
    pub fn choose_option(
        &self,
        reply: &str,
        question: &str,
        options: &[String],
    ) -> Option<Option<usize>> {
        let numbered: Vec<String> = options
            .iter()
            .enumerate()
            .map(|(i, o)| format!("{}. {o}", i + 1))
            .collect();
        let user = json!({"question": question, "options": numbered, "reply": reply}).to_string();
        let key = self.key_of(&[CHOOSE_PROMPT, &user]);
        let picked: Value = match self
            .cached(&key)
            .and_then(|t| serde_json::from_str(&t).ok())
        {
            Some(v) => v,
            None => {
                let (v, json) = self
                    .ask::<Value>(&choose_schema(), CHOOSE_PROMPT, &user)
                    .ok()?;
                self.store(&key, &json);
                v
            }
        };
        match picked["option"].as_u64() {
            Some(0) => Some(None),
            Some(n) if (n as usize) <= options.len() => Some(Some(n as usize - 1)),
            _ => None,
        }
    }
}

/// `{"option": n | null}`.
fn choose_schema() -> Value {
    json!({
        "type": "object",
        "properties": {"option": {"type": ["integer", "null"]}},
        "required": ["option"],
    })
}

/// The JSON object in a model's reply (the outermost `{...}`), checked
/// against `T`. The error says what was wrong, for the correction round.
pub fn extract<T: serde::de::DeserializeOwned>(reply: &str) -> Result<(T, String), String> {
    let a = reply.find('{').ok_or("there was no JSON object")?;
    let b = reply.rfind('}').ok_or("the JSON object was not closed")?;
    let json = &reply[a..=b];
    serde_json::from_str::<T>(json)
        .map(|t| (t, json.to_owned()))
        .map_err(|e| format!("it did not match the schema ({e})"))
}

/// The intent in a model's reply, if it is a valid one.
pub fn extract_intent(reply: &str) -> Option<Intent> {
    extract::<Intent>(reply).ok().map(|(i, _)| i)
}

impl Parser for LlmParser {
    fn name(&self) -> String {
        format!("llm:{}:{}", self.cfg.provider.name(), self.cfg.model)
    }

    fn parse(&self, text: &str, ctx: &Context) -> Intent {
        let key = self.cache_key(text, ctx);
        if let Some(i) = self
            .cached(&key)
            .and_then(|t| serde_json::from_str(&t).ok())
        {
            return i;
        }
        match self.ask::<Intent>(&Value::Null, &self.system(), &Self::user(text, ctx)) {
            Ok((intent, json)) => {
                self.store(&key, &json);
                intent
            }
            Err(e) => Intent::Unknown {
                reason: format!("The AI model could not read that ({e})."),
            },
        }
    }

    fn choose(&self, reply: &str, question: &str, options: &[String]) -> Option<Option<usize>> {
        self.choose_option(reply, question, options)
    }

    fn last_reader(&self) -> String {
        format!("AI model {}", self.label())
    }

    fn model_label(&self) -> Option<String> {
        Some(self.label())
    }
}
