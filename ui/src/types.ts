export interface MediaItem {
  project_id: string;
  filename: string;
  duration_s: number;
  source_duration_s: number;
  resolution: string;
  fps: number;
  size_bytes: number;
  source_url: string;
  timeline_hash: string;
  segments_count: number;
  captions_count: number;
  sha256: string;
}

export interface SourceMedia {
  id: string;
  filename: string;
  sha256_hash: string;
  duration_ticks: number;
  fps: number;
  width?: number;
  height?: number;
  audio_channels?: number;
  sample_rate?: number;
}

export interface TranscriptWord {
  id: string;
  word: string;
  start_ticks: number;
  end_ticks: number;
  speaker: string;
  confidence: number;
  is_filler: boolean;
  is_silence: boolean;
}

export interface Transcript {
  words: TranscriptWord[];
  language: string;
  is_mock: boolean;
}

export interface ClipSegment {
  segment_id: string;
  source_start_ticks: number;
  source_end_ticks: number;
  speed_ratio: number;
}

export interface CaptionEffect {
  id: string;
  text: string;
  anchor_word_ids: string[];
  source_start_ticks: number;
  source_end_ticks: number;
  group_id?: string;
  color: string;
  font_size: number;
  position: "bottom" | "top" | "center";
  min_duration_s: number;
  is_suppressed: boolean;
  suppression_reason?: string;
}

export interface MusicEffect {
  id: string;
  asset_url: string;
  source_start_ticks: number;
  source_end_ticks: number;
  volume: number;
  ducking: {
    enabled: boolean;
    threshold_db: number;
    attenuation_db: number;
  };
}

export interface EffectsCollection {
  captions: CaptionEffect[];
  mutes: any[];
  bleeps: any[];
  music: MusicEffect[];
  text_overlays: any[];
}

export interface TransactionRecord {
  id: string;
  instruction: string;
  operation_type: string;
  status: "applied" | "undone" | "restored";
  applied_at_step: number;
  details: Record<string, any>;
}

export interface Timeline {
  schema_version: string;
  project_id: string;
  timebase: number;
  source_media: SourceMedia;
  transcript: Transcript;
  segments: ClipSegment[];
  effects: EffectsCollection;
  transactions: TransactionRecord[];
  timeline_hash: string;
}

export interface AutoEditItem {
  item_id: string;
  category: "silence" | "filler_word" | "auto_caption" | "music";
  description: string;
  source_start_ticks: number;
  source_end_ticks: number;
  output_start_ticks?: number;
  output_end_ticks?: number;
  confidence: number;
  is_uncertain?: boolean;
  excluded: boolean;
}

export interface AutoEditPlan {
  plan_id: string;
  project_id: string;
  base_timeline_hash: string;
  created_at: number;
  current_duration_s: number;
  estimated_duration_s: number;
  items: AutoEditItem[];
  warnings?: string[];
}

export interface ChatMessage {
  id: number;
  project_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  metadata?: {
    status?: "applied" | "needs_clarification" | "rejected";
    operations?: string[];
    timeline_hash?: string;
    duration_s?: number;
    question?: string;
    options?: string[];
    warnings?: string[];
    error?: string;
  } | null;
  created_at: number;
}

export interface ModelStatus {
  active_provider: string;
  connected: boolean;
  provider: string;
  model?: string;
  available_models?: string[];
  is_real_llm?: boolean;
  api_key_configured?: boolean;
  clock_policy?: string;
  detail?: string;
}

export interface EngineResponse {
  status: "applied" | "needs_clarification" | "rejected";
  operations: string[];
  summary: string;
  question?: string;
  options?: string[];
  timeline_hash: string;
  duration_s: number;
  time_policy?: string;
  warnings?: string[];
  error?: string;
}
