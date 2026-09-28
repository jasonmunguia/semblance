// Free Cloudflare Cron Trigger: invokes the bounded Python collector on Vercel.
export default {
  async scheduled(_event, env, ctx) {
    ctx.waitUntil((async () => {
      const response = await fetch(`${env.SEMBLANCE_URL}/internal/collect`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${env.COLLECTOR_SECRET}` },
        signal: AbortSignal.timeout(55000),
      });
      if (!response.ok) throw new Error(`Collector returned HTTP ${response.status}`);
      const result = await response.json();
      // Logs record operational state only, never addresses or credentials.
      console.log(JSON.stringify({ processed: result.processed, busy: result.busy,
                                   budgetReached: result.budget_reached ?? false }));
    })());
  },
};
