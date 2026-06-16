// Jenny intro — root app

const TOTAL = 22;

// Scene timings (start, end)
const TIMING = {
  intro:     [0,    4.5],
  flood:     [4.3,  9.0],
  chat:      [8.8, 14.5],
  dashboard: [14.3, 18.5],
  outro:     [18.3, 22.0],
};

function TimestampLabel() {
  const t = useTime();
  React.useEffect(() => {
    const root = document.getElementById('video-root');
    if (root) root.setAttribute('data-screen-label', `t=${Math.floor(t)}s`);
  }, [Math.floor(t)]);
  return null;
}

function App() {
  return (
    <div id="video-root" data-screen-label="t=0s">
      <Stage width={1280} height={720} duration={TOTAL} background="#0E0B14" persistKey="jenny-intro">
        <TimestampLabel/>
        <SceneIntro     start={TIMING.intro[0]}     end={TIMING.intro[1]}/>
        <SceneFlood     start={TIMING.flood[0]}     end={TIMING.flood[1]}/>
        <SceneChat      start={TIMING.chat[0]}      end={TIMING.chat[1]}/>
        <SceneDashboard start={TIMING.dashboard[0]} end={TIMING.dashboard[1]}/>
        <SceneOutro     start={TIMING.outro[0]}     end={TIMING.outro[1]}/>
      </Stage>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
