"""Enable pgvector extension; create lesson_chunks table with HNSW index

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enable the pgvector extension (idempotent — safe to run on an existing DB).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "lesson_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.UUID(), nullable=False),
        sa.Column("course_id", sa.UUID(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        # 'content' for text-lesson body, 'transcript' for video transcript
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        # Nullable so a failed embedding call doesn't leave a useless partial row;
        # the task always populates this before committing.
        sa.Column("embedding", sa.Text(), nullable=True),  # overridden by pgvector type below
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Replace the placeholder TEXT column with the real vector(1536) type.
    # We can't declare vector(1536) via sa.Column because SQLAlchemy core doesn't
    # know this type — we use raw DDL instead.
    op.execute("ALTER TABLE lesson_chunks ALTER COLUMN embedding TYPE vector(1536) USING NULL")

    # Standard B-tree indexes for filtered queries (lesson-level re-indexing,
    # course-scoped retrieval).
    op.create_index("ix_lesson_chunks_lesson_id", "lesson_chunks", ["lesson_id"])
    op.create_index("ix_lesson_chunks_course_id", "lesson_chunks", ["course_id"])

    # HNSW approximate-nearest-neighbor index with cosine distance.
    # m=16: connections per layer (higher = better recall, more memory).
    # ef_construction=64: beam width during index build (higher = better recall, slower build).
    # These are the pgvector-recommended defaults — tune only after profiling.
    op.execute(
        """
        CREATE INDEX ix_lesson_chunks_embedding
        ON lesson_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def downgrade() -> None:
    op.drop_table("lesson_chunks")
    # Leave the extension in place — other tables might depend on it and
    # removing extensions requires superuser privileges in most hosted environments.
