import asyncio
from app.services.offer_engine import run_offer_generation

async def test():
    print('--- GamePad X Pool ---')
    res1 = await run_offer_generation('ab3321cb-81a6-4c9f-a3a3-6bcfd58e0b19')
    print('Offers generated:', res1.get('offers_generated'))
    for o in res1.get('offers', []):
        reasoning = str(o.get('strategy_reasoning', {}).get('reasoning', ''))[:100]
        print(f"Price: {o.get('price')} | Desc: {o.get('description')} | Reasoning: {reasoning}...")
        
    print('\n--- Creator X Pool ---')
    res2 = await run_offer_generation('7abdba1e-5788-4ad7-bad3-94a5e28658bc')
    print('Offers generated:', res2.get('offers_generated'))
    for o in res2.get('offers', []):
        reasoning = str(o.get('strategy_reasoning', {}).get('reasoning', ''))[:100]
        print(f"Price: {o.get('price')} | Desc: {o.get('description')} | Reasoning: {reasoning}...")

asyncio.run(test())
