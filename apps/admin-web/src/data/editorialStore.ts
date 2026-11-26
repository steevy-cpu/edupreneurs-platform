import { apply, type Command, type EditorialState, type Result } from '../domain/editorial';
import type { Persona } from '../domain/roles';
import { buildEditorialFixture } from './editorialFixtures';

/**
 * In-memory editorial store: the mock for the future FastAPI staff client.
 * Mutations change THIS object only; reloading the page restores the fixtures. No persistence, no network.
 * A real client would implement the same `dispatch` against `/v1/staff/*` and return the server's audit receipt.
 */
export class EditorialStore {
  private state: EditorialState;
  private listeners = new Set<() => void>();

  constructor(private readonly clock: () => Date = () => new Date()) {
    this.state = buildEditorialFixture();
  }

  getSnapshot = (): EditorialState => this.state;

  subscribe = (l: () => void): (() => void) => {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  };

  dispatch(cmd: Command, actor: Persona): Result {
    const { state, result } = apply(this.state, cmd, actor, this.clock());
    if (result.ok) {
      this.state = state;
      this.listeners.forEach((l) => l());
    }
    return result;
  }

  reset(): void {
    this.state = buildEditorialFixture();
    this.listeners.forEach((l) => l());
  }
}
