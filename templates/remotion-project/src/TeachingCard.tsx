import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate} from 'remotion';

const FONT_STACK =
  '"Inter", "Segoe UI", "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif';

const NAVY = '#1e3a5f';
const BLUE = '#2563eb';
const INK = '#1a2233';
const GRAY = '#5b6573';
const LIGHT = '#8a94a3';

const HALO =
  '0 1px 2px rgba(255,255,255,0.95), 0 0 8px rgba(255,255,255,0.85), 0 0 14px rgba(255,255,255,0.6)';

export const TeachingCard: React.FC<{
  keyword: string;
  ipa: string;
  meaning: string;
  definition: string;
  example: string;
}> = ({keyword, ipa, meaning, definition, example}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const slide = interpolate(frame, [0, fps * 0.45], [-720, 0], {
    extrapolateRight: 'clamp',
  });
  const fade = interpolate(frame, [0, fps * 0.35], [0, 1], {
    extrapolateRight: 'clamp',
  });

  const row = (n: string, label: string, content: React.ReactNode) => (
    <div style={{display: 'flex', alignItems: 'baseline', gap: 14, marginBottom: 8}}>
      <span style={{fontSize: 22, color: LIGHT, fontWeight: 600, width: 34, flexShrink: 0, textShadow: HALO}}>{n}</span>
      <span style={{fontSize: 20, color: GRAY, width: 56, flexShrink: 0, textShadow: HALO}}>{label}</span>
      <span style={{fontSize: 25, color: INK, fontWeight: 600, lineHeight: 1.28, flex: 1, textShadow: HALO}}>{content}</span>
    </div>
  );

  return (
    <AbsoluteFill style={{pointerEvents: 'none'}}>
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          transform: `translateY(${slide}px)`,
          opacity: fade,
          fontFamily: FONT_STACK,
        }}
      >
        <div
          style={{
            height: 46,
            backgroundColor: NAVY,
            display: 'flex',
            alignItems: 'center',
            paddingLeft: 26,
            gap: 10,
          }}
        >
          <span style={{width: 8, height: 8, borderRadius: 4, backgroundColor: '#3b82f6'}} />
          <span style={{color: '#fff', fontSize: 22, fontWeight: 700, letterSpacing: '0.08em'}}>
            范例与讲解
          </span>
        </div>

        <div style={{padding: '14px 30px 16px'}}>
          <div style={{fontSize: 19, color: BLUE, fontWeight: 700, marginBottom: 4, letterSpacing: '0.05em', textShadow: HALO}}>
            重点词汇
          </div>
          <div
            style={{
              fontSize: 54,
              fontWeight: 800,
              color: INK,
              lineHeight: 1.05,
              letterSpacing: '-0.01em',
              marginBottom: 2,
              textShadow: HALO,
            }}
          >
            {keyword}
          </div>
          <div style={{fontSize: 24, color: GRAY, fontStyle: 'italic', marginBottom: 10, textShadow: HALO}}>{ipa}</div>

          {row('01', '含义', meaning)}
          {row('02', '定义', <span style={{fontWeight: 500}}>{definition}</span>)}
          {row('03', '例句', <span style={{color: BLUE, fontWeight: 600}}>{example}</span>)}
        </div>
      </div>
    </AbsoluteFill>
  );
};
