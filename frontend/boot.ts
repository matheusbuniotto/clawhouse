/**
 * Shipped entry point: every route loads this module, which boots the shell
 * against the document markup. The router then mounts the screen for
 * `location.pathname`. Kept separate from `shell.ts` so the shell can be
 * unit-tested without the boot side effect.
 */

import { mountShell } from "./shell.js";

mountShell(document);
