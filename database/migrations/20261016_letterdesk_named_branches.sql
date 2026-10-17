-- Add human-readable outcome labels for visual branching.
-- Applied to isolated Neon staging first; production remains unchanged.
ALTER TABLE public.ld_message_edges
  ADD COLUMN IF NOT EXISTS branch_label text;

COMMENT ON COLUMN public.ld_message_edges.branch_label IS
  'Displayed name such as Message0101No for terminal/stop outcomes; never a send instruction.';
