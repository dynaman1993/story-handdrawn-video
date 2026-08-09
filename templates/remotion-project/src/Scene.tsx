import React from 'react';
import {
  AbsoluteFill,
  Audio,
  OffthreadVideo,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
} from 'remotion';
import {Caption} from './Caption';
import {TeachingCard} from './TeachingCard';
import type {Scene as SceneData} from './types';

const SUB_FONT =
  '"Inter", "Segoe UI", "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif';

const BottomSubtitle: React.FC<{text: string}> = ({text}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const opacity = interpolate(frame, [fps * 0.6, fps * 0.9], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const y = interpolate(frame, [fps * 0.6, fps * 1.0], [20, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: 70,
        display: 'flex',
        justifyContent: 'center',
        padding: '0 56px',
        opacity,
        transform: `translateY(${y}px)`,
        fontFamily: SUB_FONT,
      }}
    >
      <div
        style={{
          color: '#ffffff',
          fontSize: 38,
          fontWeight: 700,
          lineHeight: 1.25,
          textAlign: 'center',
          textShadow: '0 2px 10px rgba(0,0,0,0.85), 0 0 6px rgba(0,0,0,0.7)',
          maxWidth: 620,
        }}
      >
        {text}
      </div>
    </div>
  );
};

export const Scene: React.FC<{scene: SceneData; fps: number}> = ({scene}) => {
  const isTeaching = Boolean(scene.keyword && scene.meaning && scene.definition && scene.example);
  const bg = isTeaching ? '#0b1220' : '#F8F6EF';
  const sentence = scene.text || scene.caption || scene.narration;

  return (
    <AbsoluteFill style={{backgroundColor: bg}}>
      <OffthreadVideo
        src={staticFile(scene.motion_video)}
        muted
        style={{width: '100%', height: '100%', objectFit: 'cover'}}
      />
      <Audio src={staticFile(scene.narration_audio)} />

      {isTeaching ? (
        <>
          <div
            style={{
              position: 'absolute',
              left: 0,
              right: 0,
              bottom: 0,
              height: 260,
              background:
                'linear-gradient(to top, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0) 100%)',
            }}
          />
          <TeachingCard
            keyword={scene.keyword!}
            ipa={scene.ipa || ''}
            meaning={scene.meaning!}
            definition={scene.definition!}
            example={scene.example!}
          />
          <BottomSubtitle text={sentence} />
        </>
      ) : (
        <Caption text={scene.caption || sentence} />
      )}
    </AbsoluteFill>
  );
};
