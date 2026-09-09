// Small Cloudflare-D1-compatible adapter backed by PostgreSQL/Neon.
// This keeps the bot's existing database logic intact while running on Render.

function toPgPlaceholders(sql) {
  let index = 0;
  return sql.replace(/\?/g, () => `$${++index}`);
}

export function createD1Compat(pool) {
  return {
    prepare(sql) {
      return {
        bind(...params) {
          const query = toPgPlaceholders(sql);
          return {
            async first() {
              const result = await pool.query(query, params);
              return result.rows[0] || null;
            },
            async all() {
              const result = await pool.query(query, params);
              return { results: result.rows };
            },
            async run() {
              const result = await pool.query(query, params);
              return {
                success: true,
                meta: {
                  changes: result.rowCount,
                  last_row_id: null,
                },
              };
            },
          };
        },
        async first() {
          const result = await pool.query(toPgPlaceholders(sql));
          return result.rows[0] || null;
        },
        async all() {
          const result = await pool.query(toPgPlaceholders(sql));
          return { results: result.rows };
        },
        async run() {
          const result = await pool.query(toPgPlaceholders(sql));
          return { success: true, meta: { changes: result.rowCount, last_row_id: null } };
        },
      };
    },
  };
}
