/** Build strategy; `setPill` sets the text of the header's pill ("" hides it). */
export const Build = ({ visible }: { visible: boolean; setPill: (text: string) => void }) => <section id="workspace-builder" hidden={!visible} />;
