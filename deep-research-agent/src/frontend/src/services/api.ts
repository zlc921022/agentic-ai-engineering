const baseURL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export interface ResearchRequest {
  topic: string;
  backend?: string;
}

export interface ResearchEvent {
  run_id: string;
  seq: number;
  type: string;
  stage: string;
  status: string;
  message: string;
  step: number;
  task_id: number | null;
  agent?: string | null;
  payload: Record<string, unknown>;
  error: Record<string, unknown> | null;
  timestamp?: number;
}

export interface ResearchStreamHandlers {
  onEvent: (event: ResearchEvent) => void;
  onError?: (error: Event) => void;
  onOpen?: () => void;
}

export interface BackendInfo {
  value: string;
  label: string;
  description: string;
}

export interface BackendListResponse {
  default: string;
  backends: BackendInfo[];
}

export async function listBackends(): Promise<BackendListResponse> {
  const response = await fetch(`${baseURL}/api/backends`);
  if (!response.ok) {
    throw new Error(`获取搜索后端失败，状态码：${response.status}`);
  }
  return response.json() as Promise<BackendListResponse>;
}

export function startResearchStream(
  payload: ResearchRequest,
  handlers: ResearchStreamHandlers
): () => void {
  const url = new URL("/api/research/stream", baseURL);
  url.searchParams.set("topic", payload.topic);
  url.searchParams.set("backend", payload.backend || "hybrid");

  const source = new EventSource(url.toString());
  let closedByClient = false;

  const close = () => {
    closedByClient = true;
    source.close();
  };

  source.onopen = () => {
    handlers.onOpen?.();
  };

  source.addEventListener("research_event", (message) => {
    try {
      const event = JSON.parse(message.data) as ResearchEvent;
      handlers.onEvent(event);

      if (
        event.type === "workflow_done" ||
        event.type === "workflow_failed" ||
        event.type === "api_error"
      ) {
        close();
      }
    } catch (error) {
      console.error("解析研究事件失败：", error, message.data);
    }
  });

  source.onerror = (error) => {
    if (!closedByClient) {
      handlers.onError?.(error);
    }
  };

  return close;
}
