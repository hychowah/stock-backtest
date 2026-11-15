/** Result review of run `id`; null when no result is open. */
export const Review = ({ visible }: { visible: boolean; id: number | null }) => <section id="workspace-review" hidden={!visible} />;
