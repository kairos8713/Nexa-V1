// Program.cs
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Configuration;
using System.Text.Json;
using System.Net.Sockets;      // ✅ TcpClient
using System.Text;             // ✅ Encoding, StringBuilder
using System.IO;               // ✅ StreamReader
using System.Threading.Tasks;  // ✅ Task
using System;
using System.Collections.Generic;

var builder = WebApplication.CreateBuilder(args);

// appsettings.json (opsiyonel)
builder.Configuration.AddJsonFile("appsettings.json", optional: true);

var app = builder.Build();

// ---- Basit istek logu (isteğe bağlı ama teşhis için faydalı)
app.Use(async (ctx, next) =>
{
    Console.WriteLine($"[{DateTime.Now:HH:mm:ss}] {ctx.Request.Method} {ctx.Request.Path}");
    await next();
});

// Konfig
string T300_IP   = builder.Configuration["T300_IP"]   ?? "192.168.1.100";
int    T300_PORT = int.TryParse(builder.Configuration["T300_PORT"], out var p) ? p : 9100;
int    TIMEOUT   = int.TryParse(builder.Configuration["TIMEOUT_MS"], out var t) ? t : 8000;

// Tekil client
var t300 = new HuginClient(T300_IP, T300_PORT, TIMEOUT);

// ✅ Tek bir health/ping (çakışma yok)
app.MapGet("/health", () => Results.Json(new { ok = true, service = "HuginBridge" }));
app.MapGet("/ping",   () => Results.Text("pong"));

// ---- İş uçları
app.MapPost("/connect", async () =>
{
    var res = await t300.Connect();
    return Results.Json(res);
});

app.MapPost("/sale/start", async (SaleStartDto dto) =>
{
    var res = await t300.StartSale(dto);
    return Results.Json(res);
});

app.MapPost("/sale/pay/card", async (CardPayDto dto) =>
{
    var res = await t300.PayByCard(dto);
    return Results.Json(res);
});

app.MapPost("/sale/pay/cash", async (CashPayDto dto) =>
{
    var res = await t300.PayByCash(dto);
    return Results.Json(res);
});

app.MapPost("/sale/close", async (CloseDto dto) =>
{
    var res = await t300.Close(dto);
    return Results.Json(res);
});

app.MapGet("/sale/last_result", async () =>
{
    var res = await t300.LastResult();
    return Results.Json(res);
});

// 🔧 Debug: Ham komut gönder/cevabı gör (protokole göre payloadı sen vereceksin)
app.MapPost("/debug/raw", async (HttpContext ctx) =>
{
    using var sr = new StreamReader(ctx.Request.Body);
    var payload = await sr.ReadToEndAsync();
    var resp = await t300.SendRawAsync(payload); // ✅ public hale getirildi
    return Results.Text(resp ?? "");
});

// Port (7070 doluysa 7080 kullan)
app.Run("http://0.0.0.0:7080");


// ---------------- DTO'lar ----------------
public record SaleItemDto(string name, decimal qty, decimal price, string? taxCode = null);
public record SaleStartDto(List<SaleItemDto> items, string? note = null);
public record CardPayDto(string sale_id, decimal amount, int installment = 1);
public record CashPayDto(string sale_id, decimal amount);
public record CloseDto(string sale_id);

// ---------------- Sonuç modeli ----------------
public class BridgeResult
{
    public bool ok { get; set; }
    public string? error { get; set; }
    public string? sale_id { get; set; }
    public string? model { get; set; }
    public string? serial { get; set; }
    public string? firmware { get; set; }
    public string? fiscal_no { get; set; }
    public decimal? total { get; set; }
    public string? batch { get; set; }
    public string? stan { get; set; }
    public string? auth_code { get; set; }
    public string? status { get; set; }
}

// ---------------- HuginClient ----------------
// NOT: Buradaki <...> komutlar yer tutucu. Hugin’in gerçek LAN/SDK komutlarını
//      elindeki dökümandan dolduracağız; iskelet TCP ve debug için hazır.
public class HuginClient
{
    private readonly string ip;
    private readonly int port;
    private readonly int timeoutMs;

    // Basit bellek içi state
    private string? currentSaleId;

    public HuginClient(string ip, int port, int timeoutMs)
    {
        this.ip = ip; this.port = port; this.timeoutMs = timeoutMs;
    }

    // ✅ Debug ve iç kullanım için public yaptık
    public async Task<string> SendRawAsync(string payload)
    {
        using var client = new TcpClient();
        client.ReceiveTimeout = timeoutMs;
        client.SendTimeout = timeoutMs;

        await client.ConnectAsync(ip, port); // Örn: 192.168.1.100:9100
        using var stream = client.GetStream();

        var data = Encoding.ASCII.GetBytes(payload);
        await stream.WriteAsync(data, 0, data.Length);

        // Basit cevap oku (protokole göre boyutlandır/sonlandırıcı kullan)
        var buf = new byte[8192];
        var n = await stream.ReadAsync(buf, 0, buf.Length);
        return n > 0 ? Encoding.ASCII.GetString(buf, 0, n) : "";
    }

    public async Task<BridgeResult> Connect()
    {
        try
        {
            // Örnek/placeholder komut
            var resp = await SendRawAsync("<STATUS?>\r\n");
            return new BridgeResult { ok = true, model = "T300", serial = resp };
        }
        catch (Exception ex)
        {
            return new BridgeResult { ok = false, error = ex.Message };
        }
    }

    public async Task<BridgeResult> StartSale(SaleStartDto dto)
    {
        try
        {
            var sb = new StringBuilder();
            sb.AppendLine("<DOC:SALE>");
            foreach (var it in dto.items)
                sb.AppendLine($"<ITEM name=\"{it.name}\" qty=\"{it.qty}\" price=\"{it.price:0.00}\"/>");
            sb.AppendLine("<SUBTOTAL/>");

            var _ = await SendRawAsync(sb.ToString());
            currentSaleId = Guid.NewGuid().ToString("N");
            return new BridgeResult { ok = true, sale_id = currentSaleId };
        }
        catch (Exception ex)
        {
            return new BridgeResult { ok = false, error = ex.Message };
        }
    }

    public async Task<BridgeResult> PayByCard(CardPayDto dto)
    {
        try
        {
            var resp = await SendRawAsync($"<PAY type=\"CARD\" amount=\"{dto.amount:0.00}\" inst=\"{dto.installment}\"/>\r\n");
            // TODO: resp içinden batch/stan/auth parse
            return new BridgeResult { ok = true, sale_id = dto.sale_id, batch = "PARSE", stan = "PARSE", auth_code = "PARSE" };
        }
        catch (Exception ex)
        {
            return new BridgeResult { ok = false, error = ex.Message, sale_id = dto.sale_id };
        }
    }

    public async Task<BridgeResult> PayByCash(CashPayDto dto)
    {
        try
        {
            var _ = await SendRawAsync($"<PAY type=\"CASH\" amount=\"{dto.amount:0.00}\"/>\r\n");
            return new BridgeResult { ok = true, sale_id = dto.sale_id };
        }
        catch (Exception ex)
        {
            return new BridgeResult { ok = false, error = ex.Message, sale_id = dto.sale_id };
        }
    }

    public async Task<BridgeResult> Close(CloseDto dto)
    {
        try
        {
            var resp = await SendRawAsync("<CLOSE/>\r\n");
            // TODO: resp'tan fiscal no/total parse
            return new BridgeResult { ok = true, sale_id = dto.sale_id, fiscal_no = "PARSE", total = null };
        }
        catch (Exception ex)
        {
            return new BridgeResult { ok = false, error = ex.Message, sale_id = dto.sale_id };
        }
    }

    public async Task<BridgeResult> LastResult()
    {
        try
        {
            var resp = await SendRawAsync("<LAST_RESULT/>\r\n");
            return new BridgeResult { ok = true, status = resp };
        }
        catch (Exception ex)
        {
            return new BridgeResult { ok = false, error = ex.Message };
        }
    }
}
