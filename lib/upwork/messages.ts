import type { ParseJobResult } from "./parser"

export type UpworkContentMessage =
  | { type: "GET_CURRENT_JOB" }
  | { type: "SCROLL_TO_APPLY" }

export type UpworkContentResponse = ParseJobResult | boolean
