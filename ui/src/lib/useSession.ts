import { useCallback, useEffect, useRef, useState } from "react";

import { bootstrap } from "./api.ts";
import { applyEvent, createTranscript, loadHistory, type TranscriptState } from "./transcript.ts";
import type { Attachment, PermissionMode, ServerMessage, Session } from "./types.ts";

export type Connection = "connecting" | "open" | "closed";

export interface SessionHandle {
  transcript: TranscriptState;
  session: Session | null;
  connection: Connection;
  error: string | null;
  clearError: () => void;
  send: (text: string, attachments?: Attachment[]) => void;
  cancel: () => void;
  approve: (requestId: string, response: "approve" | "approve_for_session" | "reject") => void;
  setMode: (mode: PermissionMode) => void;
}

/** One live session: its transcript, kept current over a reconnecting socket. */
export function useSession(sessionId: string | null, onSessionChange?: (session: Session) => void): SessionHandle {
  const transcriptRef = useRef<TranscriptState>(createTranscript());
  const [, setVersion] = useState(0);
  const [session, setSession] = useState<Session | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [error, setError] = useState<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const frame = useRef<number | null>(null);
  const changeRef = useRef(onSessionChange);
  changeRef.current = onSessionChange;

  // Streaming deltas arrive far faster than frames; render once per frame.
  const schedule = useCallback(() => {
    if (frame.current != null) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = null;
      setVersion((v) => v + 1);
    });
  }, []);

  useEffect(() => {
    transcriptRef.current = createTranscript();
    setSession(null);
    setError(null);
    setVersion((v) => v + 1);
    if (!sessionId) return;
    let closed = false;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = async () => {
      setConnection("connecting");
      try {
        await bootstrap();
      } catch (e) {
        setError(String((e as Error).message));
      }
      if (closed) return;
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      const socket = new WebSocket(`${scheme}://${location.host}/api/sessions/${sessionId}/ws`);
      socketRef.current = socket;
      socket.onopen = () => {
        retry = 0;
        setConnection("open");
      };
      socket.onmessage = (message) => {
        const data = JSON.parse(message.data) as ServerMessage;
        if (data.type === "hello") {
          transcriptRef.current = loadHistory(data.history, data.pending_approvals);
          setSession(data.session);
          changeRef.current?.(data.session);
          setVersion((v) => v + 1);
        } else if (data.type === "event") {
          const t = transcriptRef.current;
          if (data.event.type === "SessionUpdated") {
            setSession(data.event.payload as Session);
            changeRef.current?.(data.event.payload as Session);
          }
          if (applyEvent(t, data.event)) {
            if (data.event.type === "TurnFinished" || data.event.type === "UserPrompt" || data.event.type === "ModeChanged" || data.event.type === "RuntimeStatus") {
              setSession((current) => {
                if (!current) return current;
                const next: Session = { ...current, running: t.running };
                if (data.event.type === "ModeChanged") next.permission_mode = data.event.payload.mode;
                if (data.event.type === "RuntimeStatus") {
                  next.runtime_state = data.event.payload.state;
                  if (data.event.payload.state === "ready") next.runtime = { ...current.runtime, ...data.event.payload };
                }
                changeRef.current?.(next);
                return next;
              });
            }
            schedule();
          }
        } else if (data.type === "session") {
          setSession(data.session);
          changeRef.current?.(data.session);
        } else if (data.type === "error") {
          setError(data.message);
        }
      };
      socket.onclose = (event) => {
        socketRef.current = null;
        if (closed) return;
        setConnection("closed");
        if (event.code === 4404) {
          setError("This session no longer exists.");
          return;
        }
        retry += 1;
        timer = setTimeout(connect, Math.min(8000, 500 * 2 ** Math.min(retry, 4)));
      };
    };
    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [sessionId]);

  const post = useCallback((payload: unknown) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      setError("Not connected to the server — reconnecting…");
      return;
    }
    socket.send(JSON.stringify(payload));
  }, []);

  return {
    transcript: transcriptRef.current,
    session,
    connection,
    error,
    clearError: () => setError(null),
    send: (text, attachments) =>
      post({ type: "prompt", text, attachments: attachments?.map(({ name, mime, data }) => ({ name, mime, data })) }),
    cancel: () => post({ type: "cancel" }),
    approve: (requestId, response) => post({ type: "approval", request_id: requestId, response }),
    setMode: (mode) => post({ type: "set_mode", mode }),
  };
}
