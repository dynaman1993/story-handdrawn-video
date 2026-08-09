import React from 'react';
import {AbsoluteFill, Sequence} from 'remotion';
import {Scene} from './Scene';
import storyboard from './storyboard';

export const StoryVideo: React.FC = () => {
  let cursor = 0;
  return (
    <AbsoluteFill style={{backgroundColor: '#F8F6EF'}}>
      {storyboard.scenes.map((s) => {
        const frames = Math.round(s.duration_sec * storyboard.fps);
        const from = cursor;
        cursor += frames;
        return (
          <Sequence key={s.id} from={from} durationInFrames={frames}>
            <Scene scene={s} fps={storyboard.fps} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
