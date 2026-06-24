import Dexie, { type Table } from 'dexie';
import type { ExportPayload, QuestionRecord, SessionRecord } from './types';

const EXPORT_FORMAT = 'cgl-buddy-mcq-db';
const EXPORT_VERSION = 1;
const MAX_QUESTIONS = 5000;
const MAX_SESSIONS = 200;

class CglBuddyDb extends Dexie {
  questions!: Table<QuestionRecord & { id: string; key: string }, string>;
  sessions!: Table<SessionRecord & { id: string; timestamp: string }, string>;

  constructor() {
    super('cgl-buddy-mobile');
    this.version(1).stores({
      questions: 'id, key, subject, source, added_at',
      sessions: 'id, timestamp',
    });
  }
}

export const db = new CglBuddyDb();

export function normalizeQuestion(text: string): string {
  return (text || '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .replace(/[^\p{L}\p{N}\s_]/gu, '')
    .trim();
}

async function keyFor(text: string): Promise<string> {
  const encoded = new TextEncoder().encode(normalizeQuestion(text));
  const digest = await crypto.subtle.digest('SHA-1', encoded);
  const bytes = [...new Uint8Array(digest)].slice(0, 8);
  return bytes.map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

function newId(): string {
  return crypto.randomUUID().replace(/-/g, '').slice(0, 12);
}

function cleanRecord(record: QuestionRecord, source: string): QuestionRecord | null {
  const question = String(record.question || '').trim();
  const options = Array.isArray(record.options) ? record.options.map((option) => String(option)) : [];
  const correctIndex = Number(record.correct_index);
  if (!question || options.length !== 4 || !Number.isInteger(correctIndex) || correctIndex < 0 || correctIndex > 3) {
    return null;
  }
  const subject = String(record.subject || record.category || 'General');
  return {
    question,
    options,
    correct_index: correctIndex,
    subject,
    category: subject,
    topic: String(record.topic || ''),
    difficulty: String(record.difficulty || 'medium'),
    explanation: String(record.explanation || ''),
    source: String(record.source || source),
  };
}

export async function storedQuestions(): Promise<QuestionRecord[]> {
  return db.questions.orderBy('added_at').toArray();
}

export async function addQuestions(records: QuestionRecord[], source = 'Imported database'): Promise<{ added: number; skipped: number }> {
  const bundled = await loadBundledQuestions();
  const bundledKeys = new Set(await Promise.all(bundled.map((question) => keyFor(question.question))));
  const stored = await db.questions.toArray();
  const seen = new Set<string>([...bundledKeys, ...stored.map((question) => question.key)]);
  let added = 0;
  let skipped = 0;
  const now = new Date().toISOString();
  const inserts: Array<QuestionRecord & { id: string; key: string }> = [];

  for (const raw of records) {
    const record = cleanRecord(raw, source);
    if (!record) {
      skipped += 1;
      continue;
    }
    const key = await keyFor(record.question);
    if (seen.has(key)) {
      skipped += 1;
      continue;
    }
    seen.add(key);
    inserts.push({ ...record, id: newId(), key, source: record.source || source, added_at: now });
    added += 1;
  }

  if (inserts.length) {
    await db.questions.bulkAdd(inserts);
    const count = await db.questions.count();
    if (count > MAX_QUESTIONS) {
      const overflow = count - MAX_QUESTIONS;
      const oldest = await db.questions.orderBy('added_at').limit(overflow).primaryKeys();
      await db.questions.bulkDelete(oldest as string[]);
    }
  }
  return { added, skipped };
}

export async function deleteStoredQuestion(id: string): Promise<void> {
  await db.questions.delete(id);
}

export async function exportDatabase(): Promise<ExportPayload> {
  const questions = await storedQuestions();
  return {
    format: EXPORT_FORMAT,
    version: EXPORT_VERSION,
    exported_at: new Date().toISOString(),
    question_count: questions.length,
    questions: questions.map((question) => ({
      question: question.question,
      options: question.options,
      correct_index: question.correct_index,
      subject: question.subject || question.category || 'General',
      topic: question.topic || '',
      difficulty: question.difficulty || 'medium',
      explanation: question.explanation || '',
      source: question.source || 'Imported database',
    })),
  };
}

export function recordsFromPayload(payload: unknown): QuestionRecord[] {
  if (Array.isArray(payload)) return payload.filter((item): item is QuestionRecord => typeof item === 'object' && item !== null);
  if (payload && typeof payload === 'object' && Array.isArray((payload as { questions?: unknown }).questions)) {
    return (payload as { questions: unknown[] }).questions.filter((item): item is QuestionRecord => typeof item === 'object' && item !== null);
  }
  throw new Error('Database JSON must be a list of questions or contain a questions array.');
}

export async function importDatabasePayload(payload: unknown): Promise<{ added: number; skipped: number; found: number }> {
  const records = recordsFromPayload(payload);
  const result = await addQuestions(records, 'Imported database');
  return { found: records.length, ...result };
}

export async function saveSession(record: SessionRecord): Promise<void> {
  const entry = {
    ...record,
    id: record.id || newId(),
    timestamp: record.timestamp || new Date().toISOString(),
  };
  await db.sessions.put(entry);
  const sessions = await db.sessions.orderBy('timestamp').toArray();
  if (sessions.length > MAX_SESSIONS) {
    const remove = sessions.slice(0, sessions.length - MAX_SESSIONS).map((session) => session.id);
    await db.sessions.bulkDelete(remove);
  }
}

export async function listSessions(): Promise<SessionRecord[]> {
  return db.sessions.orderBy('timestamp').reverse().toArray();
}

export async function clearSessions(): Promise<void> {
  await db.sessions.clear();
}

export async function loadBundledQuestions(): Promise<QuestionRecord[]> {
  const response = await fetch('/data/mcq_bank.json', { cache: 'no-cache' });
  if (!response.ok) throw new Error(`Could not load bundled MCQ bank (${response.status}).`);
  const payload = await response.json();
  const records = recordsFromPayload(payload);
  return records.map((record) => ({
    ...record,
    subject: record.subject || record.category || 'General',
    category: record.subject || record.category || 'General',
    topic: record.topic || '',
    difficulty: record.difficulty || 'medium',
    explanation: record.explanation || '',
    source: record.source || 'Bundled bank',
  }));
}
