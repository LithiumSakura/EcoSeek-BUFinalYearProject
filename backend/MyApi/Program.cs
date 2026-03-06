var builder = WebApplication.CreateBuilder(args);

builder.Services.AddControllers();

// CORS — allow your GitHub Pages domain
builder.Services.AddCors(options =>
{
    options.AddPolicy("AllowGitHubPages", policy =>
    {
        policy.WithOrigins("https://LithiumSakura.github.io")
              .AllowAnyHeader()
              .AllowAnyMethod();
    });
});

var app = builder.Build();

app.UseCors("AllowGitHubPages");
app.MapControllers();
app.Run();
