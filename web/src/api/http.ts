export class ApiFailure extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function failureText(error: unknown): string {
  if (error instanceof ApiFailure) return error.message;
  if (error && typeof error === "object" && "detail" in error) {
    const detail = (error as { detail: unknown }).detail;
    if (typeof detail === "string" && detail) return detail;
    if (detail && typeof detail === "object" && "code" in detail) {
      const body = detail as { code?: string; message?: string };
      if (body.code && body.message) return `${body.code}: ${body.message}`;
      return body.code ?? body.message ?? "Request failed";
    }
  }
  if (error instanceof Error && error.message) return error.message;
  return "Request failed";
}

type CallResult<T> = {
  data?: T;
  error?: unknown;
  response: Response;
};

export async function call<T>(pending: Promise<CallResult<T>>): Promise<T> {
  const result = await pending;
  if (!result.response.ok) {
    throw new ApiFailure(result.response.status, failureText(result.error));
  }
  return result.data as T;
}

/** OpenAPI renders a free-form dict as an empty record. The API still accepts a normal object. */
export function loose<T>(value: T): Record<string, never> {
  return value as unknown as Record<string, never>;
}
