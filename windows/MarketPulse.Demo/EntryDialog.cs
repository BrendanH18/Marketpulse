using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;

namespace MarketPulse.Demo;

/// <summary>A labelled, keyboard-accessible form which keeps validation errors beside the inputs.</summary>
internal sealed class EntryDialog : Window
{
    private readonly StackPanel _fields = new() { Spacing = 12 };
    private readonly TextBlock _error = new() { TextWrapping = Avalonia.Media.TextWrapping.Wrap };
    private readonly Button _submit;
    private readonly Button _cancel = new() { Content = "Cancel", IsCancel = true };
    private bool _saving;
    private bool _saved;
    private bool _frozen;
    public Func<Task>? Submit { get; set; }

    public EntryDialog(string title, string action = "Save")
    {
        Title = title;
        Width = 520;
        MaxHeight = 760;
        SizeToContent = SizeToContent.Height;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        _submit = new Button { Content = action };
        _submit.Click += async (_, _) =>
        {
            if (_saving || Submit is null) return;
            _saving = true;
            _fields.IsEnabled = false;
            _submit.IsEnabled = false;
            _cancel.IsEnabled = false;
            _error.Text = "Working…";
            try { await Submit(); _saved = true; Close(); }
            catch (Exception error) { _error.Text = error.Message; }
            finally { _saving = false; _fields.IsEnabled = !_frozen; _submit.IsEnabled = true; _cancel.IsEnabled = true; }
        };
        _cancel.Click += (_, _) => Close();
        Closing += (_, args) => { if (_saving && !_saved) args.Cancel = true; };
        var buttons = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 12, HorizontalAlignment = HorizontalAlignment.Right };
        buttons.Children.Add(_cancel);
        buttons.Children.Add(_submit);
        var body = new StackPanel { Margin = new Thickness(24), Spacing = 18 };
        body.Children.Add(new TextBlock { Text = title, FontSize = 22, FontWeight = Avalonia.Media.FontWeight.SemiBold });
        body.Children.Add(_fields);
        body.Children.Add(_error);
        body.Children.Add(buttons);
        Content = new ScrollViewer { Content = body };
    }

    public TextBox Text(string label, string value = "", string? hint = null)
    {
        var input = new TextBox { Text = value, PlaceholderText = hint };
        Add(label, input);
        return input;
    }

    public ComboBox Choice(string label, IEnumerable<string> values, string? selected = null)
    {
        var items = values.ToArray();
        var input = new ComboBox { ItemsSource = items, SelectedItem = selected, HorizontalAlignment = HorizontalAlignment.Stretch };
        if (input.SelectedIndex < 0 && items.Length > 0) input.SelectedIndex = 0;
        Add(label, input);
        return input;
    }

    public CheckBox Check(string label, bool value = false)
    {
        var input = new CheckBox { Content = label, IsChecked = value };
        _fields.Children.Add(input);
        return input;
    }

    public void Explain(string text) => _fields.Children.Add(new TextBlock { Text = text, TextWrapping = Avalonia.Media.TextWrapping.Wrap });
    public void Freeze() { _frozen = true; _fields.IsEnabled = false; }
    private void Add(string label, Control input)
    {
        var panel = new StackPanel { Spacing = 4 };
        panel.Children.Add(new Label { Content = label, Target = input });
        panel.Children.Add(input);
        _fields.Children.Add(panel);
    }
}
