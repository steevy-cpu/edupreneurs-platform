/**
 * API types. Everything here is derived from the generated OpenAPI definitions
 * (`schema.d.ts`, produced by `npm run gen:api` from packages/contracts/openapi.json).
 * Do not hand-write response shapes: change the backend contract and regenerate.
 */
import type { components } from './schema';

type Schemas = components['schemas'];

export type Locale = 'fr' | 'ht';
export type MeResponse = Schemas['MeResponse'];
export type CatalogResponse = Schemas['CatalogResponse'];
export type CatalogCourse = Schemas['CatalogCourse'];
export type CatalogLesson = Schemas['CatalogLesson'];
export type LessonResponse = Schemas['LessonResponse'];
export type PracticeQuestion = Schemas['PracticeQuestion'];
export type SyncOperation = Schemas['SyncOperation'];
export type PushRequest = Schemas['PushRequest'];
export type PushResponse = Schemas['PushResponse'];
export type OperationResult = Schemas['OperationResult'];
export type PullResponse = Schemas['PullResponse'];
export type ChangeItem = Schemas['ChangeItem'];
export type ErrorResponse = Schemas['ErrorResponse'];
