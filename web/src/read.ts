import { useEffect, useState } from "preact/hooks";
import { ApiFailure } from "./client.ts";

/** The state of one read: still loading, its value, or why it failed. */
export type Read<T> =
  | { state: "loading" }
  | { state: "done"; value: T }
  | { state: "failed"; failure: ApiFailure };

/** The reply of one read for the current arguments: loading, value or failure.
 *  A reply that arrives after the arguments changed is dropped.
 *
 *  `read` runs again only when an element of `args` changes (compared as
 *  `useEffect` compares them, with Object.is), and the state is `loading`
 *  until its reply arrives. Each result is kept with the arguments it was read
 *  for, so the render in which the arguments change already gives `loading`,
 *  never the reply to the old arguments. Pass numbers and strings in `args`:
 *  an object or array made during the render is new each time, so the read
 *  would start again at every render and never finish. A failure is an
 *  ApiFailure (see client.ts). */
export function useRead<T>(read: () => Promise<T>, args: unknown[]): Read<T> {
  const [result, setResult] = useState<{ args: unknown[]; read: Read<T> } | null>(null);
  useEffect(() => {
    let current = true;
    read().then(
      (value) => current && setResult({ args, read: { state: "done", value } }),
      (failure: unknown) => current && setResult({ args, read: { state: "failed", failure: asFailure(failure) } }),
    );
    return () => {
      current = false;
    };
  }, args);
  const same = result !== null && result.args.length === args.length && result.args.every((arg, i) => Object.is(arg, args[i]));
  return same ? result.read : { state: "loading" };
}

/** A thrown value as an ApiFailure; the client throws nothing else, so any
 *  other value is a fault of the page itself. */
export function asFailure(thrown: unknown): ApiFailure {
  return thrown instanceof ApiFailure ? thrown : new ApiFailure(0, String(thrown), "");
}
