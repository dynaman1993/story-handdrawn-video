export type Scene = {
  id: string;
  caption?: string;
  text?: string;
  text_zh?: string;
  narration: string;
  narration_audio: string;
  motion_video: string;
  duration_sec: number;
  num_frames?: number;
  prompt_snapshot?: string;
  // 教学卡字段（textbook 风格，存在则渲染 TeachingCard 叠层）
  keyword?: string;
  ipa?: string;
  meaning?: string;
  definition?: string;
  example?: string;
};

export type Storyboard = {
  title: string;
  lang?: string;
  style?: string;
  width: number;
  height: number;
  fps: number;
  frame_rate_video?: number;
  scenes: Scene[];
};
