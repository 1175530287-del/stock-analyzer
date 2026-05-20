#!/usr/bin/env python3
"""
Stock Analyzer - 输入股票代码，获得实时分析和建议
"""
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import urllib.request
import urllib.parse
import json
import os
from datetime import datetime, timezone, timedelta

app = Flask(__name__, static_folder='static')
CORS(app)

BJT = timezone(timedelta(hours=8))

# 代码前缀映射
def search_stock(keyword):
    """搜索股票代码（通过名称）"""
    url = f'http://suggest3.sinajs.cn/suggest/type=11&key={urllib.parse.quote(keyword)}'
    req = urllib.request.Request(url, headers={
        'Referer': 'https://finance.sina.com.cn',
        'User-Agent': 'Mozilla/5.0'
    })
    resp = urllib.request.urlopen(req, timeout=10)
    data = resp.read().decode('gbk')
    
    if '=' not in data or '"' not in data:
        return None
    
    value = data.split('="')[1].strip('";')
    parts = value.split(',')
    
    if len(parts) < 4 or not parts[2]:
        return None
    
    raw_code = parts[2]  # 纯数字代码
    # 只返回6位数字代码
    if raw_code.isdigit() and len(raw_code) == 6:
        return raw_code
    return None

def get_prefix(code):
    if code.startswith('68'):
        return 'sh'
    elif code.startswith('6'):
        return 'sh'
    elif code.startswith('30'):
        return 'sz'
    elif code.startswith('00'):
        return 'sz'
    elif code.startswith('0'):
        return 'sz'
    elif code.startswith('3'):
        return 'sz'
    else:
        return 'sz'  # default

def fetch_stock(code):
    """从新浪API获取股票数据"""
    prefix = get_prefix(code)
    url = f'http://hq.sinajs.cn/list={prefix}{code}'
    req = urllib.request.Request(url, headers={'Referer': 'https://finance.sina.com.cn'})
    resp = urllib.request.urlopen(req, timeout=10)
    data = resp.read().decode('gbk')
    
    if '=' not in data or '";' not in data:
        return None
    
    parts = data.split('=')[1].strip('";\n').split(',')
    
    if len(parts) < 32:
        return None
    
    name = parts[0]
    open_p = float(parts[1]) if parts[1] else 0
    prev_close = float(parts[2]) if parts[2] else 0
    price = float(parts[3]) if parts[3] else 0
    high = float(parts[4]) if parts[4] else 0
    low = float(parts[5]) if parts[5] else 0
    vol = int(parts[8]) if parts[8] else 0  # 手
    amt = float(parts[9]) if parts[9] else 0  # 元
    date_str = parts[30] if len(parts) > 30 else ''
    time_str = parts[31] if len(parts) > 31 else ''
    
    if prev_close == 0:
        return None
    
    change = price - prev_close
    change_pct = change / prev_close * 100
    amp = (high - low) / prev_close * 100
    
    exchange = 'SH' if prefix == 'sh' else 'SZ'
    
    return {
        'code': code,
        'exchange': exchange,
        'name': name,
        'price': price,
        'change': round(change, 2),
        'change_pct': round(change_pct, 2),
        'open': open_p,
        'high': high,
        'low': low,
        'prev_close': prev_close,
        'volume': vol,
        'amount': round(amt / 100000000, 2),  # 亿元
        'amplitude': round(amp, 2),
        'time': f'{date_str} {time_str}',
    }


def generate_analysis(data, hold=False):
    """根据数据生成分析建议"""
    price = data['price']
    change_pct = data['change_pct']
    change = data['change']
    amp = data['amplitude']
    vol = data['volume']
    amt = data['amount']
    high = data['high']
    low = data['low']
    open_p = data['open']
    prev_close = data['prev_close']
    name = data['name']
    code = data['code']
    
    lines = []
    
    # 基础信息
    if change_pct > 0:
        icon = '📈'
    elif change_pct < 0:
        icon = '📉'
    else:
        icon = '➖'
    
    lines.append(f'{icon} {name}({code})  {price:.2f}  {change_pct:+.2f}%')
    lines.append(f'   开{open_p:.2f}  高{high:.2f}  低{low:.2f}  昨收{prev_close:.2f}')
    lines.append(f'   涨跌{change:+.2f}  振幅{amp:.2f}%  成交{amt:.1f}亿')
    lines.append('')
    
    is_up = change_pct > 0
    
    # --- 日内走势分析 ---
    if is_up and amp > 8:
        lines.append('⚡ 日内走势：冲高回落，波动剧烈')
        if price < high * 0.99:
            lines.append(f'   从最高{high:.2f}回落至{price:.2f}，短线抛压明显')
        else:
            lines.append('   封板强势，多头占绝对优势')
    elif is_up and amp > 5:
        lines.append('📊 日内走势：震荡上行，趋势偏强')
        lines.append(f'   低点{low:.2f}→高点{high:.2f}，涨幅{((high-low)/low*100):.1f}%')
    elif is_up:
        lines.append('📊 日内走势：温和上涨，波动不大')
    elif not is_up and amp > 5 and price > low:
        lines.append('📊 日内走势：探底回升，低位有承接')
        lines.append(f'   最低{low:.2f}后反弹至{price:.2f}')
    elif not is_up and amp > 5:
        lines.append('📊 日内走势：单边下跌，弱势明显')
    elif not is_up:
        lines.append('📊 日内走势：窄幅下跌，交投清淡')
    elif amp <= 2:
        lines.append('📊 日内走势：窄幅震荡，观望为主')
    
    # --- 成交量分析 ---
    if amt > 100:
        vol_desc = f'巨量({amt:.0f}亿级别)，分歧极大'
    elif amt > 50:
        vol_desc = f'放量({amt:.0f}亿)，交投活跃'
    elif amt > 20:
        vol_desc = f'量能正常({amt:.0f}亿)'
    elif amt > 5:
        vol_desc = f'缩量({amt:.0f}亿)，人气不足'
    else:
        vol_desc = f'地量({amt:.1f}亿)，极度冷清'
    
    if is_up and amt > 50:
        vol_desc += '，资金正在涌入'
    elif is_up and amt <= 5:
        vol_desc += '，反弹可能无量'
    elif not is_up and amt > 50:
        vol_desc += '，抛压沉重'
    elif not is_up and amt <= 5:
        vol_desc += '，跌不动但也没人买'
    
    lines.append(f'📊 成交量：{vol_desc}')
    lines.append('')
    
    # --- 技术面 ---
    # 支撑位和压力位（基于日内数据估算）
    support1 = round(low * 0.98, 2)
    support2 = round(low * 0.95, 2)
    resist1 = round(high * 1.02, 2)
    resist2 = round(high * 1.05, 2)
    mid = round((high + low) / 2, 2)
    
    lines.append('📐 技术位：')
    lines.append(f'   压力位: {resist1}')
    lines.append(f'   中轴线: {mid}')
    lines.append(f'   支撑位: {support1}')
    lines.append('')
    
    # --- 综合建议（区分持仓状态） ---
    if hold:
        # ===== 已持仓 =====
        lines.append('📋 持仓分析：')
        
        if is_up and amp > 8 and price < high * 0.99:
            lines.append(f'   今日大涨后回落，短线可能还有震荡')
            lines.append(f'   如果盈利已较多，可考虑在{resist1}附近减仓')
            lines.append(f'   中长线可继续持有，止损设在{support2}')
            action = '持有观察，冲高可减'
            risk = '中等'
        elif is_up and price >= high * 0.99:
            lines.append(f'   强势涨停/接近涨停，明天可能继续冲高')
            lines.append(f'   如果明天不能连板，短线可考虑止盈')
            lines.append(f'   止损上移至今日开盘价{open_p:.2f}')
            action = '持有看明天'
            risk = '偏低'
        elif is_up:
            lines.append(f'   今日稳健上行，趋势正常')
            lines.append(f'   持仓不动，跌破{support1}再考虑减仓')
            action = '继续持有'
            risk = '偏低'
        elif not is_up and price > low:
            lines.append(f'   今日探底回升，低位有资金承接')
            lines.append(f'   如果已在成本附近，可再观察一天')
            lines.append(f'   坚决守住止损线{support2}')
            action = '观察一天，跌破止损'
            risk = '中等'
        elif not is_up:
            lines.append(f'   今日单边走弱，短线不乐观')
            lines.append(f'   如果已跌破成本价且放量，建议减仓')
            lines.append(f'   关键防线: {support1}')
            action = '弱势，考虑减仓'
            risk = '偏高'
        else:
            lines.append(f'   今日窄幅震荡，多空平衡')
            lines.append(f'   持仓等待方向选择，破位再动')
            action = '持有观望'
            risk = '中等'
        
        lines.append(f'   💡 建议：{action}')
        
    else:
        # ===== 未持仓 =====
        if is_up and amp > 8 and price < high * 0.99:
            lines.append(f'💡 建议：短线已高，不宜追涨')
            lines.append(f'   策略：等回踩{mid}附近再考虑')
            lines.append(f'   止损参考: {support1}  目标: {resist1}')
            risk = '偏高'
        elif is_up and amp > 5:
            lines.append(f'💡 建议：趋势偏强，可等回调介入')
            lines.append(f'   策略：回踩{round(price * 0.97, 2)}可轻仓')
            lines.append(f'   止损参考: {round(price * 0.95, 2)}')
            risk = '中等'
        elif is_up:
            lines.append(f'💡 建议：温和上行，趋势健康')
            lines.append(f'   策略：回踩{support1}附近可关注')
            risk = '偏低'
        elif not is_up and price > low:
            lines.append(f'💡 建议：探底回升，有企稳迹象')
            lines.append(f'   策略：观察明天能否站稳{support1}')
            risk = '中等'
        elif not is_up:
            lines.append(f'💡 建议：弱势调整，暂时观望')
            lines.append(f'   策略：等明确企稳信号再入场')
            lines.append(f'   关键支撑: {support1}  跌破回避')
            risk = '偏高'
        else:
            lines.append(f'💡 建议：方向不明，暂时观望')
            risk = '中等'
    
    lines.append(f'   风险等级: {risk}')
    lines.append('')
    lines.append('⚠️ 仅供参考，不构成投资建议')
    
    return '\n'.join(lines)


@app.route('/')
def index():
    resp = send_from_directory('static', 'index.html')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp


@app.route('/api/analyze')
def analyze():
    raw = request.args.get('code', '').strip()
    
    if not raw:
        return jsonify({'error': '请输入股票代码或名称'}), 400
    
    code = raw
    
    # 如果不是6位纯数字，按名称搜索
    if not (raw.isdigit() and len(raw) == 6):
        try:
            result = search_stock(raw)
            if not result:
                return jsonify({'error': f'未找到"{raw}"，请试试输入股票代码'}), 404
            code = result
        except Exception as e:
            return jsonify({'error': f'搜索失败: {str(e)}'}), 500
    
    try:
        stock_data = fetch_stock(code)
    except Exception as e:
        return jsonify({'error': f'获取数据失败: {str(e)}'}), 500
    
    if not stock_data:
        return jsonify({'error': '未找到该股票，请检查代码是否正确'}), 404
    
    hold = request.args.get('hold', '0') == '1'
    
    analysis = generate_analysis(stock_data, hold=hold)
    
    return jsonify({
        'data': stock_data,
        'analysis': analysis
    })


@app.route('/api/hot_sectors')
def hot_sectors():
    """获取板块热度排行"""
    import re
    try:
        url = 'http://q.10jqka.com.cn/thshy/'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=10)
        html = resp.read().decode('gbk')
        
        rows = re.findall(r'<tr[^>]*>.*?</tr>', html, re.DOTALL)
        lines = ['📊 板块热度排行', '']
        
        hot = []
        cold = []
        
        for row in rows:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            if len(cells) >= 6:
                name = re.sub(r'<[^>]+>', '', cells[1]).strip()
                chg_str = cells[2].strip()
                flow_str = cells[5].strip()
                if name and chg_str:
                    try:
                        chg = float(chg_str)
                        flow = float(flow_str) if flow_str else 0
                        flow_text = f'净流入{flow:+.1f}亿' if abs(flow) > 0 else ''
                        entry = (chg, name, chg, flow_text)
                        if chg > 0:
                            hot.append(entry)
                        else:
                            cold.append(entry)
                    except ValueError:
                        pass
        
        hot.sort(key=lambda x: x[0], reverse=True)
        cold.sort(key=lambda x: x[0])
        
        lines.append('🔥 领涨板块')
        for _, name, chg, flow in hot[:8]:
            flow_text = f'  {flow}' if flow else ''
            lines.append(f'   {name:<12} {chg:>+5.2f}%{flow_text}')
        
        if cold:
            lines.append('')
            lines.append('❄️ 领跌板块')
            for _, name, chg, flow in cold[:5]:
                flow_text = f'  {flow}' if flow else ''
                lines.append(f'   {name:<12} {chg:>+5.2f}%{flow_text}')
        
        lines.append('')
        lines.append('⚠️ 数据来源：同花顺')
        
        return jsonify({'data': '\n'.join(lines)})
        
    except Exception as e:
        return jsonify({'error': f'获取板块数据失败: {str(e)}'}), 500


@app.route('/api/news')
def stock_news():
    """获取个股近期新闻"""
    code = request.args.get('code', '').strip()
    if not code:
        return jsonify({'error': '请输入股票代码'}), 400
    
    prefix = get_prefix(code)
    symbol = f'{prefix}{code}'
    
    import re
    
    try:
        url = f'https://finance.sina.com.cn/realstock/company/{symbol}/nc.shtml'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=10)
        html = resp.read()
        try:
            html = html.decode('gbk')
        except:
            html = html.decode('utf-8', errors='replace')
        
        # 提取所有新浪财经的新闻链接
        items = re.findall(
            r'<a[^>]*href=\"(https?://finance\.sina[^\"]+)\"[^>]*>(.*?)</a>',
            html, re.DOTALL
        )
        
        skip_kw = ['更多', '新浪', '快用', 'var ', '配置', '雷达', 'level2',
                   'APP', '意见', '举报', '反馈', '违法']
        
        # 利好/利空关键词
        good_kw = ['涨停', '大涨', '新高', '突破', '利好', '增长', '受益', '扩产',
                   '签约', '中标', '合作', '增持', '买入', '推荐', '扭亏', '景气',
                   '回升', '放量', '拉升', '爆发', '加仓', '上调', '溢价']
        bad_kw = ['跌停', '大跌', '减持', '利空', '下降', '亏损', '风险', '下跌',
                  '监管', '调查', '处罚', '卖出', '负面', '降级', '下调', '回落',
                  '出货', '流出', '做空', '违约', '暂停', '终止']
        
        def classify(title):
            for kw in good_kw:
                if kw in title:
                    return 'good'
            for kw in bad_kw:
                if kw in title:
                    return 'bad'
            return 'neutral'
        
        news = []
        for url, title in items:
            title = re.sub(r'<[^>]+>', '', title).strip()
            if len(title) < 12:
                continue
            if any(k in title for k in skip_kw):
                continue
            if title not in [n['title'] for n in news]:
                # 尝试从链接里拿完整标题（新浪标题可能被截断）
                full_title = title
                try:
                    art_req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    art_resp = urllib.request.urlopen(art_req, timeout=3)
                    art_html = art_resp.read()
                    try:
                        art_html = art_html.decode('gbk')
                    except:
                        art_html = art_html.decode('utf-8', errors='replace')
                    # 找文章标题
                    mt = re.search(r'<title>(.*?)</title>', art_html, re.DOTALL)
                    if mt:
                        t = mt.group(1).strip()
                        # 去掉站点名后缀和标签
                        t = re.sub(r'_\d+_\d+$', '', t)
                        t = re.sub(r'\s*[-_|]\s*新浪财经.*$', '', t)
                        t = re.sub(r'\|[^|]+$', '', t)  # 去掉末尾标签
                        if len(t) > len(full_title):
                            full_title = t
                except:
                    pass
                
                news.append({
                    'title': full_title,
                    'url': url,
                    'sentiment': classify(full_title)
                })
                if len(news) >= 15:
                    break
        
        if not news:
            return jsonify({'news': [], 'message': '暂无相关新闻'})
        
        # 分类整理
        good_news = [n for n in news if n['sentiment'] == 'good']
        bad_news = [n for n in news if n['sentiment'] == 'bad']
        neutral_news = [n for n in news if n['sentiment'] == 'neutral']
        
        return jsonify({
            'good': good_news[:5],
            'bad': bad_news[:5],
            'neutral': neutral_news[:3]
        })
        
    except Exception as e:
        return jsonify({'error': f'获取新闻失败: {str(e)}'}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
# Railway deploy fix
