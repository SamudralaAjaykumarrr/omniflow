import { API_BASE, get } from "./client";

const BASE = API_BASE.prometheus;

export interface PrometheusSample {
  metric: Record<string, string>;
  value: [number, string];
}

export interface PrometheusMatrixSample {
  metric: Record<string, string>;
  values: [number, string][];
}

interface PrometheusResponse<T> {
  status: "success" | "error";
  data: { resultType: string; result: T[] };
  error?: string;
}

/** GET /api/v1/query — instant query, e.g. current Kafka consumer lag. */
export async function instantQuery(promQL: string): Promise<PrometheusSample[]> {
  const data = await get<PrometheusResponse<PrometheusSample>>(
    BASE,
    `/api/v1/query?query=${encodeURIComponent(promQL)}`,
  );
  if (data.status !== "success") {
    throw new Error(data.error ?? "Prometheus query failed");
  }
  return data.data.result;
}

/** GET /api/v1/query_range — for small trend sparklines. */
export async function rangeQuery(
  promQL: string,
  startSeconds: number,
  endSeconds: number,
  stepSeconds: number,
): Promise<PrometheusMatrixSample[]> {
  const params = new URLSearchParams({
    query: promQL,
    start: String(startSeconds),
    end: String(endSeconds),
    step: String(stepSeconds),
  });
  const data = await get<PrometheusResponse<PrometheusMatrixSample>>(
    BASE,
    `/api/v1/query_range?${params.toString()}`,
  );
  if (data.status !== "success") {
    throw new Error(data.error ?? "Prometheus range query failed");
  }
  return data.data.result;
}

/** First scalar value out of an instant-query result, or `undefined` if empty (no scrape yet). */
export function firstValue(samples: PrometheusSample[]): number | undefined {
  const raw = samples[0]?.value?.[1];
  return raw === undefined ? undefined : Number(raw);
}

export function sumValues(samples: PrometheusSample[]): number {
  return samples.reduce((acc, s) => acc + Number(s.value[1]), 0);
}
