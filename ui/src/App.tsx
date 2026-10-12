import { useEffect, useState } from "react";

import { Brand } from "./components/TuraBrand.tsx";

// root's UI is the board, which lives in chamber (`chamber board`, on 127.0.0.1:7878):
// root starts it next to itself, and this page sends you there.
// (Sessions, learning, flows and trust are still in the code, off the UI.)

const BOARD = "http://127.0.0.1:7878";

export function App() {
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    document.documentElement.dataset.theme = localStorage.getItem("root:theme") || "dark";
    let tries = 0;
    const timer = setInterval(() => {
      // An opaque answer is enough to know the board is up; it starts with root.
      fetch(`${BOARD}/api/board`, { mode: "no-cors" }).then(
        () => location.replace(BOARD + location.hash),
        () => {
          tries += 1;
          if (tries > 6) setMissing(true);
        },
      );
    }, 500);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="redirectPage">
      <Brand />
      {missing ? (
        <p>
          The board is not running. Start it with <code>chamber board</code>, or install chamber with the command a teammate sent you.
        </p>
      ) : (
        <p>Opening the board…</p>
      )}
    </div>
  );
}
