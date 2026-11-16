interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env?: ImportMetaEnv;
}

/** Vite bundles a worker with its imports and returns the URL of the built file. */
declare module "*?worker&url" {
  const url: string;
  export default url;
}
