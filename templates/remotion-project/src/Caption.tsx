import React from 'react';
import {AbsoluteFill, staticFile} from 'remotion';

const FONT_URL = staticFile('fonts/MaShanZheng-Regular.ttf');

function formatLines(text: string, maxPerLine = 14, maxLines = 3): string[] {
  const out: string[] = [];
  let remaining = text.trim();
  while (remaining) {
    if (remaining.length <= maxPerLine) {
      out.push(remaining);
      break;
    }
    const window = remaining.slice(0, maxPerLine + 1);
    let cut = Math.max(
      window.lastIndexOf('，'),
      window.lastIndexOf('、'),
      window.lastIndexOf('；'),
      window.lastIndexOf('：'),
      window.lastIndexOf(' '),
    );
    if (cut < maxPerLine * 0.5) cut = maxPerLine;
    else cut += 1;
    out.push(remaining.slice(0, cut).trim());
    remaining = remaining.slice(cut).trim();
    if (remaining && /^[。！？!?；;：:,，、]/.test(remaining)) {
      out[out.length - 1] += remaining[0];
      remaining = remaining.slice(1).trim();
    }
  }
  if (out.length > maxLines) return out.slice(0, maxLines);
  return out;
}

export const Caption: React.FC<{text: string}> = ({text}) => {
  const lines = formatLines(text);
  return (
    <AbsoluteFill
      style={{
        justifyContent: 'flex-end',
        alignItems: 'center',
        paddingBottom: 90,
        pointerEvents: 'none',
      }}
    >
      <style>{`
        @font-face {
          font-family: 'MaShanZheng';
          src: url(${FONT_URL}) format('truetype');
          font-display: block;
        }
      `}</style>
      <div
        style={{
          fontFamily: 'MaShanZheng, "Ma Shan Zheng", serif',
          fontSize: 54,
          lineHeight: 1.25,
          color: '#171714',
          textAlign: 'center',
          textShadow:
            '0 0 8px #F8F6EF, 0 0 8px #F8F6EF, 0 0 8px #F8F6EF, 0 0 8px #F8F6EF',
          padding: '0 80px',
          transform: 'rotate(-0.35deg)',
          whiteSpace: 'pre-line',
        }}
      >
        {lines.join('\n')}
      </div>
    </AbsoluteFill>
  );
};
