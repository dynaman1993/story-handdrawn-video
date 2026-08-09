import React from 'react';
import {Composition} from 'remotion';
import {StoryVideo} from './StoryVideo';
import storyboard from './storyboard';

export const Root: React.FC = () => {
  const totalFrames = storyboard.scenes.reduce(
    (acc, s) => acc + Math.round(s.duration_sec * storyboard.fps),
    0,
  );

  return (
    <Composition
      id="StoryVideo"
      component={StoryVideo}
      width={storyboard.width}
      height={storyboard.height}
      fps={storyboard.fps}
      durationInFrames={Math.max(1, totalFrames)}
      defaultProps={{}}
    />
  );
};
