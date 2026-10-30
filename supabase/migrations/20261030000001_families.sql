-- Families: parents see how their children are doing in the Cheetah Moon
-- games (cheetahmoongames.com/family, app/family.py).
--
-- A parent asks for a child by the email on the child's account
-- (family_asks; `email` in lower case). Nothing is shared until the child,
-- signed in, says yes: then the ask becomes a link (family_links). Either of
-- them can undo a link.
CREATE TABLE family_asks (
    parent_id   UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email       TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (parent_id, email)
);

CREATE INDEX idx_family_asks_email ON family_asks(email);

CREATE TABLE family_links (
    parent_id   UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    child_id    UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (parent_id, child_id),
    CHECK (parent_id <> child_id)
);

CREATE INDEX idx_family_links_child_id ON family_links(child_id);

ALTER TABLE family_asks ENABLE ROW LEVEL SECURITY;
ALTER TABLE family_links ENABLE ROW LEVEL SECURITY;
